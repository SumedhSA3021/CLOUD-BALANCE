"""Round Robin Baseline Scheduler."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.models.schemas import SchedulerDecisionMeta, SchedulerName, Task, Telemetry
from app.schedulers.base import BaseScheduler, BatchAssignmentResult, InFlightTracker


class RoundRobinScheduler(BaseScheduler):
    """Baseline scheduler using a cyclic pointer across workers, ignoring resource load."""

    def __init__(self, in_flight_tracker: InFlightTracker | None = None) -> None:
        super().__init__(
            name=SchedulerName.ROUND_ROBIN.value,
            in_flight_tracker=in_flight_tracker,
        )
        self._cursor: int = 0

    def assign(
        self,
        batch: Sequence[Task],
        workers: Sequence[Telemetry],
        record_in_flight: bool = True,
    ) -> BatchAssignmentResult:
        """Assign tasks cyclically regardless of worker CPU/RAM utilization."""
        start_ns = time.perf_counter_ns()
        now_mono = time.monotonic()

        if not workers:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            return BatchAssignmentResult(
                assignments={},
                meta=SchedulerDecisionMeta(
                    scheduler=self.name,
                    status="NO_WORKERS",
                    solver_latency_ms=round(elapsed_ms, 3),
                    projected_peak_cpu=0.0,
                    projected_peak_mem_pct=0.0,
                    degraded=True,
                    warning="No active workers available in cluster.",
                ),
            )

        num_workers = len(workers)
        proj_cpus: list[float] = []
        proj_mems: list[float] = []
        total_mems: list[float] = []

        for w in workers:
            if_cpu, if_mem, _ = self.in_flight.get_worker_in_flight(w.worker_id, now_mono)
            proj_cpus.append(float(w.cpu_percent) + if_cpu)
            proj_mems.append(float(w.memory_used_mb) + if_mem)
            total_mems.append(max(1.0, float(w.memory_total_mb)))

        assignments: dict[str, str] = {}
        for task in batch:
            idx = self._cursor % num_workers
            self._cursor = (self._cursor + 1) % (num_workers * 1_000_000)
            chosen_worker = workers[idx]
            assignments[task.task_id] = chosen_worker.worker_id
            proj_cpus[idx] += task.cpu_demand_pct
            proj_mems[idx] += task.mem_demand_mb
            if record_in_flight:
                self.in_flight.reserve(task, chosen_worker.worker_id, now_mono)

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        peak_cpu = min(100.0, max(proj_cpus) if proj_cpus else 0.0)
        peak_mem_pct = min(
            100.0,
            max((proj_mems[j] / total_mems[j]) * 100.0 for j in range(num_workers)),
        )

        return BatchAssignmentResult(
            assignments=assignments,
            meta=SchedulerDecisionMeta(
                scheduler=self.name,
                status="OPTIMAL",
                solver_latency_ms=round(elapsed_ms, 3),
                projected_peak_cpu=round(peak_cpu, 2),
                projected_peak_mem_pct=round(peak_mem_pct, 2),
                degraded=False,
            ),
        )

