"""Lightweight Scheduler State & Virtual Worker Decay Service."""

from __future__ import annotations

import asyncio
import contextlib

from app.core.logging import get_logger
from app.models.schemas import SchedulerName
from app.services.cluster_state import ClusterStateService

logger = get_logger("service.scheduler_state")


class SchedulerStateService:
    """Lightweight holder for active_scheduler_name, configured_lambda, and virtual worker decay."""

    def __init__(
        self,
        cluster_state: ClusterStateService,
        default_scheduler: str = "ortools_milp",
        seed_demo_workers: bool = True,
        decay_interval_sec: float = 0.5,
    ) -> None:
        self._cluster_state = cluster_state
        self._seed_demo_workers = seed_demo_workers
        self._decay_interval_sec = decay_interval_sec
        self._active_scheduler_name: str = (
            SchedulerName.ROUND_ROBIN.value
            if "round_robin" in str(default_scheduler).lower()
            else SchedulerName.ORTOOLS_MILP.value
        )
        self._configured_lambda: float = 12.0
        self._running: bool = False
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def queue_depth(self) -> int:
        return 0

    @property
    def active_scheduler_name(self) -> str:
        return self._active_scheduler_name

    @property
    def configured_lambda(self) -> float:
        return self._configured_lambda

    def set_scheduler(self, scheduler_name: SchedulerName | str) -> str:
        """Set active scheduler name (`ortools_milp` or `round_robin`)."""
        resolved = str(SchedulerName(scheduler_name).value)
        self._active_scheduler_name = resolved
        logger.info("scheduler_hot_swapped", active_scheduler=resolved)
        return resolved

    def set_configured_lambda(self, lambda_rate: float) -> None:
        self._configured_lambda = max(0.0, float(lambda_rate))

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
                await asyncio.sleep(self._decay_interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("scheduler_state_loop_error", error=str(exc))
                await asyncio.sleep(0.2)

    async def start(self) -> None:
        """Start background virtual-worker decay loop if demo seeding is enabled."""
        if self._running:
            return
        self._running = True
        if self._seed_demo_workers:
            await self._cluster_state.seed_virtual_workers_if_empty()
            self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop background virtual-worker decay loop."""
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
