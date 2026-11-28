"""Async Task Dispatcher with Retries, Timeouts, and Automatic Failover Re-Solving."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

import httpx
import numpy as np
from tenacity import AsyncRetrying, stop_after_attempt, wait_fixed

from app.core.logging import get_logger
from app.models.schemas import DispatchPayload, Task, Telemetry
from app.schedulers.base import BaseScheduler
from app.services.cluster_state import ClusterStateService
from app.services.history import HistoryService

logger = get_logger("service.dispatcher")


def _run_virtual_np_dot(dim: int = 80) -> float:
    """Fast real np.dot computation for virtual standalone local mode."""
    rng = np.random.default_rng(42)
    a = rng.standard_normal((dim, dim), dtype=np.float64)
    b = rng.standard_normal((dim, dim), dtype=np.float64)
    c = np.dot(a, b)
    return float(c[0, 0])


class DispatcherService:
    """Dispatches tasks to internal Worker VMs (:8001/execute) with retries and failover."""

    def __init__(
        self,
        cluster_state: ClusterStateService,
        history: HistoryService,
        timeout_sec: float = 12.0,
        max_retries: int = 2,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cluster_state = cluster_state
        self._history = history
        self._timeout_sec = timeout_sec
        self._max_retries = max_retries
        self._external_client = http_client

    async def _post_to_worker(
        self,
        worker: Telemetry,
        payload: DispatchPayload,
    ) -> float:
        """Send POST http://<worker_ip>:<port>/execute with retries, returning execution_ms."""
        if worker.worker_id in self._cluster_state.killed_workers:
            raise httpx.ConnectError(f"Worker {worker.worker_id} is unreachable (killed)")

        if worker.ip_address == "virtual":
            start_ns = time.perf_counter_ns()
            # Reflect active workload on the virtual worker in Redis
            busy_cpu = min(98.0, round(worker.cpu_percent + payload.cpu_demand_pct * 0.65, 2))
            busy_mem = min(
                worker.memory_total_mb,
                round(worker.memory_used_mb + payload.mem_demand_mb * 0.65, 2),
            )
            busy_mem_pct = min(100.0, round((busy_mem / worker.memory_total_mb) * 100.0, 2))
            busy_telemetry = worker.model_copy(
                update={
                    "cpu_percent": busy_cpu,
                    "memory_used_mb": busy_mem,
                    "memory_percent": busy_mem_pct,
                    "active_task_count": worker.active_task_count + 1,
                    "load_avg_1m": round(busy_cpu / 25.0, 2),
                }
            )
            await self._cluster_state.update_telemetry(busy_telemetry)
            await asyncio.to_thread(_run_virtual_np_dot, 64)
            await asyncio.sleep(min(0.15, payload.duration_sec * 0.05))
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            return round(elapsed_ms, 2)

        url = f"http://{worker.ip_address}:{worker.port}/execute"
        body = payload.model_dump(mode="json")

        client = self._external_client or httpx.AsyncClient(timeout=self._timeout_sec)
        owns_client = self._external_client is None
        try:
            attempts = max(1, self._max_retries + 1)
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_fixed(0.05),
                reraise=True,
            ):
                with attempt:
                    resp = await client.post(url, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                    return float(data.get("execution_ms", 10.0))
        finally:
            if owns_client:
                await client.aclose()
        return 0.0

    async def dispatch_task(
        self,
        task: Task,
        initial_worker: Telemetry,
        candidate_workers: Sequence[Telemetry],
        scheduler: BaseScheduler,
    ) -> tuple[str, str, float]:
        """Dispatch `task` to `initial_worker`; on failure evict worker and re-solve across remaining.

        Returns:
            Tuple of `(final_worker_id, final_status, execution_ms)`.
        """
        payload = DispatchPayload(
            task_id=task.task_id,
            duration_sec=task.duration_sec,
            matrix_dim=task.matrix_dim,
            cpu_demand_pct=task.cpu_demand_pct,
            mem_demand_mb=task.mem_demand_mb,
        )

        try:
            exec_ms = await self._post_to_worker(initial_worker, payload)
            scheduler.in_flight.release(task.task_id)
            updated = self._history.update_assignment_status(
                task_id=task.task_id,
                status="COMPLETED",
                execution_ms=exec_ms,
                assigned_worker_id=initial_worker.worker_id,
            )
            await self._history.sync_assignment_to_redis(updated)
            logger.info(
                "task_execution_completed",
                task_id=task.task_id,
                client_id=task.client_id,
                worker_id=initial_worker.worker_id,
                execution_ms=exec_ms,
            )
            return initial_worker.worker_id, "COMPLETED", exec_ms
        except Exception as exc:
            logger.warning(
                "worker_dispatch_failed_triggering_failover",
                task_id=task.task_id,
                failed_worker=initial_worker.worker_id,
                error=str(exc),
            )
            # Release reservation on failed worker and evict from Redis cluster state
            scheduler.in_flight.release(task.task_id)
            await self._cluster_state.evict_worker(initial_worker.worker_id)

            # Re-solve excluding the failed worker
            remaining = [
                w
                for w in candidate_workers
                if w.worker_id != initial_worker.worker_id
                and w.worker_id not in self._cluster_state.killed_workers
            ]
            if not remaining:
                self._history.update_assignment_status(
                    task_id=task.task_id,
                    status="FAILED",
                    execution_ms=0.0,
                    assigned_worker_id=initial_worker.worker_id,
                )
                return initial_worker.worker_id, "FAILED", 0.0

            failover_res = scheduler.assign([task], remaining, record_in_flight=True)
            new_worker_id = failover_res.assignments.get(task.task_id, remaining[0].worker_id)
            new_worker = next(
                (w for w in remaining if w.worker_id == new_worker_id),
                remaining[0],
            )
            try:
                exec_ms = await self._post_to_worker(new_worker, payload)
                scheduler.in_flight.release(task.task_id)
                updated = self._history.update_assignment_status(
                    task_id=task.task_id,
                    status="COMPLETED",
                    execution_ms=exec_ms,
                    assigned_worker_id=new_worker.worker_id,
                )
                await self._history.sync_assignment_to_redis(updated)
                logger.info(
                    "worker_failover_succeeded",
                    task_id=task.task_id,
                    from_worker=initial_worker.worker_id,
                    to_worker=new_worker.worker_id,
                )
                return new_worker.worker_id, "COMPLETED", exec_ms
            except Exception as exc2:
                scheduler.in_flight.release(task.task_id)
                logger.error(
                    "worker_failover_exhausted",
                    task_id=task.task_id,
                    error=str(exc2),
                )
                updated_fail = self._history.update_assignment_status(
                    task_id=task.task_id,
                    status="FAILED",
                    execution_ms=0.0,
                    assigned_worker_id=new_worker.worker_id,
                )
                await self._history.sync_assignment_to_redis(updated_fail)
                return new_worker.worker_id, "FAILED", 0.0

