"""Least Connections Baseline Scheduler."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.models.schemas import SchedulerDecisionMeta, SchedulerName, Task, Telemetry
from app.schedulers.base import BaseScheduler, BatchAssignmentResult, InFlightTracker


class LeastConnectionsScheduler(BaseScheduler):
    """Baseline scheduler routing each task to the worker with minimum active_task_count (incl. in-flight)."""

    def __init__(self, in_flight_tracker: InFlightTracker | None = None) -> None:
        super().__init__(
            name=SchedulerName.LEAST_CONNECTIONS.value,
            in_flight_tracker=in_flight_tracker,
        )

    def assign(
        self,
        batch: Sequence[Task],
        workers: Sequence[Telemetry],
        record_in_flight: bool = True,
    ) -> BatchAssignmentResult:
        """Assign tasks greedily to the worker with the fewest active + in-flight tasks."""
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
        active_counts: list[int] = []

        for w in workers:
            if_cpu, if_mem, if_count = self.in_flight.get_worker_in_flight(w.worker_id, now_mono)
            proj_cpus.append(float(w.cpu_percent) + if_cpu)
            proj_mems.append(float(w.memory_used_mb) + if_mem)
            total_mems.append(max(1.0, float(w.memory_total_mb)))
            active_counts.append(int(w.active_task_count) + if_count)

        assignments: dict[str, str] = {}
        for task in batch:
            # Pick worker with minimum active connection count
            best_j = min(range(num_workers), key=lambda j: (active_counts[j], j))
            chosen_worker = workers[best_j]
            assignments[task.task_id] = chosen_worker.worker_id
            active_counts[best_j] += 1
            proj_cpus[best_j] += task.cpu_demand_pct
            proj_mems[best_j] += task.mem_demand_mb
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

