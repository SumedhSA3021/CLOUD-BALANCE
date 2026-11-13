"""Micro-Batcher Service (200ms window or max 20 tasks) with Pluggable Scheduler Hot-Swap."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.core.logging import get_logger
from app.models.schemas import Assignment, SchedulerName, Task, Telemetry
from app.schedulers.base import BaseScheduler, InFlightTracker
from app.schedulers.least_connections import LeastConnectionsScheduler
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.schedulers.round_robin import RoundRobinScheduler
from app.services.client_stats import ClientStatsService
from app.services.cluster_state import ClusterStateService
from app.services.dispatcher import DispatcherService
from app.services.history import HistoryService

logger = get_logger("service.batcher")


class MicroBatcherService:
    """Queues incoming tasks, micro-batches every 200ms (or 20 tasks), schedules, and dispatches."""

    def __init__(
        self,
        cluster_state: ClusterStateService,
        dispatcher: DispatcherService,
        history: HistoryService,
        client_stats: ClientStatsService,
        in_flight_tracker: InFlightTracker,
        max_queue_depth: int = 500,
        rate_limit_per_sec: int = 300,
        batch_window_ms: int = 200,
        batch_max_size: int = 20,
        solver_time_limit_ms: int = 50,
        cpu_cap_pct: float = 85.0,
        mem_cap_pct: float = 90.0,
        default_scheduler: str = "ortools_milp",
        seed_demo_workers: bool = True,
    ) -> None:
        self._cluster_state = cluster_state
        self._dispatcher = dispatcher
        self._history = history
        self._client_stats = client_stats
        self._in_flight = in_flight_tracker
        self._max_queue_depth = max_queue_depth
        self._rate_limit_per_sec = rate_limit_per_sec
        self._batch_window_sec = batch_window_ms / 1000.0
        self._batch_max_size = batch_max_size
        self._seed_demo_workers = seed_demo_workers

        self._schedulers: dict[str, BaseScheduler] = {
            SchedulerName.ORTOOLS_MILP.value: ORToolsMILPScheduler(
                time_limit_ms=solver_time_limit_ms,
                cpu_cap_pct=cpu_cap_pct,
                mem_cap_pct=mem_cap_pct,
                in_flight_tracker=self._in_flight,
            ),
            SchedulerName.ROUND_ROBIN.value: RoundRobinScheduler(
                in_flight_tracker=self._in_flight,
            ),
            SchedulerName.LEAST_CONNECTIONS.value: LeastConnectionsScheduler(
                in_flight_tracker=self._in_flight,
            ),
        }
        self._active_scheduler_name = (
            default_scheduler
            if default_scheduler in self._schedulers
            else SchedulerName.ORTOOLS_MILP.value
        )

        self._queue: deque[tuple[Task, float]] = deque()
        self._recent_accept_times: deque[float] = deque()
        self._paused: bool = False
        self._configured_lambda: float = 12.0
        self._running: bool = False
        self._loop_task: asyncio.Task[None] | None = None
        self._bg_dispatch_tasks: set[asyncio.Task[object]] = set()

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def active_scheduler_name(self) -> str:
        return self._active_scheduler_name

    @property
    def active_scheduler(self) -> BaseScheduler:
        return self._schedulers[self._active_scheduler_name]

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def configured_lambda(self) -> float:
        return self._configured_lambda

    def set_scheduler(self, scheduler_name: SchedulerName | str) -> str:
        """Hot-swap the active scheduler at runtime."""
        resolved = str(SchedulerName(scheduler_name).value)
        self._active_scheduler_name = resolved
        if resolved == SchedulerName.ROUND_ROBIN.value:
            rr_sched = self._schedulers.get(resolved)
            if hasattr(rr_sched, "reset"):
                rr_sched.reset()
        logger.info("scheduler_hot_swapped", active_scheduler=resolved)
        return resolved

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        logger.info("batcher_pause_toggled", paused=paused)

    def set_configured_lambda(self, lambda_rate: float) -> None:
        self._configured_lambda = max(0.0, float(lambda_rate))

    def enqueue(self, task: Task) -> int:
        """Validate rate limit & backpressure, then append `task` to the micro-batch queue.

        Raises:
            HTTPException(429): When queue capacity (`max_queue_depth`) or rate limit is exceeded.
        """
        now = time.monotonic()
        cutoff = now - 1.0
        while self._recent_accept_times and self._recent_accept_times[0] < cutoff:
            self._recent_accept_times.popleft()

        if len(self._recent_accept_times) >= self._rate_limit_per_sec:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({self._rate_limit_per_sec} req/s)",
            )

        if len(self._queue) >= self._max_queue_depth:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Task queue full (depth={len(self._queue)}/{self._max_queue_depth})",
            )

        self._recent_accept_times.append(now)
        self._queue.append((task, now))
        self._client_stats.record_enqueue(task.client_id, now)
        return len(self._queue)

    async def flush_one_batch(self, wait_for_dispatch: bool = False) -> list[Assignment]:
        """Drain up to `batch_max_size` tasks, solve placement via active scheduler, and dispatch."""
        if self._paused or not self._queue:
            return []

        workers: list[Telemetry] = await self._cluster_state.get_active_workers()
        if not workers and self._seed_demo_workers:
            workers = await self._cluster_state.seed_virtual_workers_if_empty()

        if not workers:
            return []

        batch_entries: list[tuple[Task, float]] = []
        while self._queue and len(batch_entries) < self._batch_max_size:
            batch_entries.append(self._queue.popleft())

        batch_tasks = [entry[0] for entry in batch_entries]
        scheduler = self.active_scheduler
        res = scheduler.assign(batch_tasks, workers, record_in_flight=True)

        logger.info(
            "micro_batch_scheduled",
            batch_size=len(batch_tasks),
            scheduler=scheduler.name,
            solver_status=res.meta.status,
            solver_latency_ms=res.meta.solver_latency_ms,
            projected_peak_cpu=res.meta.projected_peak_cpu,
            degraded=res.meta.degraded,
            assignments=res.assignments,
        )

        now_mono = time.monotonic()
        worker_by_id = {w.worker_id: w for w in workers}
        created_assignments: list[Assignment] = []
        dispatch_coroutines = []

        for task, enqueued_mono in batch_entries:
            assigned_wid = res.assignments.get(task.task_id)
            if not assigned_wid or assigned_wid not in worker_by_id:
                self._client_stats.record_dropped(task.client_id)
                continue

            queue_wait_ms = max(0.0, (now_mono - enqueued_mono) * 1000.0)
            self._client_stats.record_assigned(
                client_id=task.client_id,
                worker_id=assigned_wid,
                queue_wait_ms=queue_wait_ms,
            )

            assignment = Assignment(
                task_id=task.task_id,
                client_id=task.client_id,
                task_type=task.task_type,
                cpu_demand_pct=task.cpu_demand_pct,
                mem_demand_mb=task.mem_demand_mb,
                assigned_worker_id=assigned_wid,
                scheduler=scheduler.name,
                solver_latency_ms=res.meta.solver_latency_ms,
                queue_wait_ms=round(queue_wait_ms, 2),
                status="DEGRADED_ASSIGNED" if res.meta.degraded else "ASSIGNED",
                degraded=res.meta.degraded,
                timestamp=datetime.now(UTC),
            )
            await self._history.record_assignment(assignment, warning=res.meta.warning)
            created_assignments.append(assignment)

            target_worker = worker_by_id[assigned_wid]
            coro = self._dispatcher.dispatch_task(
                task=task,
                initial_worker=target_worker,
                candidate_workers=workers,
                scheduler=scheduler,
            )
            if wait_for_dispatch:
                dispatch_coroutines.append(coro)
            else:
                bg_task: asyncio.Task[object] = asyncio.create_task(coro)
                self._bg_dispatch_tasks.add(bg_task)
                bg_task.add_done_callback(self._bg_dispatch_tasks.discard)

        if wait_for_dispatch and dispatch_coroutines:
            await asyncio.gather(*dispatch_coroutines)

        # Keep virtual workers' TTL refreshed in standalone local mode
        if self._seed_demo_workers and all(w.ip_address == "virtual" for w in workers):
            for w in workers:
                await self._cluster_state.update_telemetry(w)

        return created_assignments

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if self._seed_demo_workers:
                    workers = await self._cluster_state.get_active_workers()
                    if not workers:
                        await self._cluster_state.seed_virtual_workers_if_empty()
                    elif all(w.ip_address == "virtual" for w in workers):
                        for w in workers:
                            decayed_cpu = max(9.0, round(w.cpu_percent * 0.92, 2))
                            decayed_mem = max(580.0, round(w.memory_used_mb * 0.95, 2))
                            decayed_mem_pct = round((decayed_mem / w.memory_total_mb) * 100.0, 2)
                            await self._cluster_state.update_telemetry(
                                w.model_copy(
                                    update={
                                        "cpu_percent": decayed_cpu,
                                        "memory_used_mb": decayed_mem,
                                        "memory_percent": decayed_mem_pct,
                                        "active_task_count": max(0, w.active_task_count - 1),
                                    }
                                )
                            )

                if len(self._queue) >= self._batch_max_size:
                    await self.flush_one_batch(wait_for_dispatch=False)
                else:
                    await asyncio.sleep(self._batch_window_sec)
                    if self._queue:
                        await self.flush_one_batch(wait_for_dispatch=False)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("micro_batcher_loop_error", error=str(exc))
                await asyncio.sleep(0.1)

    async def start(self) -> None:
        """Start background micro-batching loop."""
        if self._running:
            return
        self._running = True
        if self._seed_demo_workers:
            await self._cluster_state.seed_virtual_workers_if_empty()
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop background micro-batching loop and await in-flight tasks."""
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        if self._bg_dispatch_tasks:
            await asyncio.gather(*self._bg_dispatch_tasks, return_exceptions=True)
            self._bg_dispatch_tasks.clear()

