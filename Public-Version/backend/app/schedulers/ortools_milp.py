"""OR-Tools Mixed-Integer Linear Programming (MILP) Multi-Resource Scheduler."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from ortools.linear_solver import pywraplp

from app.core.logging import get_logger
from app.models.schemas import SchedulerDecisionMeta, SchedulerName, Task, Telemetry
from app.schedulers.base import BaseScheduler, BatchAssignmentResult, InFlightTracker

logger = get_logger("scheduler.ortools_milp")

SOLVER_CALL_COUNT: int = 0


def get_solver_call_count() -> int:
    """Return the cumulative number of times the OR-Tools MILP solver was executed."""
    return SOLVER_CALL_COUNT


def reset_solver_call_count() -> None:
    """Reset the MILP solver call counter to 0."""
    global SOLVER_CALL_COUNT
    SOLVER_CALL_COUNT = 0


class ORToolsMILPScheduler(BaseScheduler):
    """Adaptive multi-resource MILP scheduler minimizing peak worker CPU utilization.

    Formulation:
      - Binary decision variables: X[i, j] in {0, 1} for task i, worker j.
      - Continuous minimax peak CPU variable: Z in [0, 100].
      - Continuous minimax peak Memory % variable: M in [0, 100].
      - Constraints:
          1) Single assignment: sum_j X[i, j] == 1 for all i
          2) Hard CPU cap: current_cpu_j + in_flight_cpu_j + sum_i cpu_i * X[i, j] <= 85.0
          3) Hard RAM cap: current_mem_j + in_flight_mem_j + sum_i mem_i * X[i, j] <= 0.90 * total_mem_j
          4) Peak CPU bound: projected_cpu_j <= Z for all j
          5) Peak RAM % bound: projected_mem_pct_j <= M for all j
      - Objective:
          Minimize Z + 0.001 * M
      - Fallback on INFEASIBLE:
          Greedily route each task in the batch to the worker with the lowest projected load,
          marking degraded=True and emitting a dashboard warning.
    """

    def __init__(
        self,
        time_limit_ms: int = 50,
        cpu_cap_pct: float = 85.0,
        mem_cap_pct: float = 90.0,
        in_flight_tracker: InFlightTracker | None = None,
    ) -> None:
        super().__init__(
            name=SchedulerName.ORTOOLS_MILP.value,
            in_flight_tracker=in_flight_tracker,
        )
        self.time_limit_ms = time_limit_ms
        self.cpu_cap_pct = cpu_cap_pct
        self.mem_cap_pct = mem_cap_pct
        self._rr_tie_break: int = 0

    def _create_solver(self) -> pywraplp.Solver | None:
        solver = pywraplp.Solver.CreateSolver("CBC")
        if solver is None:
            solver = pywraplp.Solver.CreateSolver("SCIP")
        return solver

    def _degraded_fallback(
        self,
        batch: Sequence[Task],
        workers: Sequence[Telemetry],
        base_cpus: list[float],
        base_mems: list[float],
        total_mems: list[float],
        elapsed_ms: float,
        reason: str,
        record_in_flight: bool,
        tie_break_costs: list[float] | None = None,
    ) -> BatchAssignmentResult:
        """Greedy lowest-projected-load assignment when the MILP is infeasible."""
        proj_cpus = list(base_cpus)
        proj_mems = list(base_mems)
        assignments: dict[str, str] = {}
        tb_costs = tie_break_costs if tie_break_costs is not None else [0.0] * len(workers)

        for task in batch:
            best_j = 0
            best_score = float("inf")
            for j in range(len(workers)):
                candidate_cpu = proj_cpus[j] + task.cpu_demand_pct
                candidate_mem_pct = ((proj_mems[j] + task.mem_demand_mb) / total_mems[j]) * 100.0
                # Penalize cap violations heavily while still picking lowest projected node
                over_cpu = max(0.0, candidate_cpu - self.cpu_cap_pct) * 10.0
                over_mem = max(0.0, candidate_mem_pct - self.mem_cap_pct) * 10.0
                score = (
                    candidate_cpu
                    + 0.05 * candidate_mem_pct
                    + over_cpu
                    + over_mem
                    + (tb_costs[j] if j < len(tb_costs) else 0.0)
                )
                if score < best_score:
                    best_score = score
                    best_j = j

            chosen_worker = workers[best_j]
            assignments[task.task_id] = chosen_worker.worker_id
            proj_cpus[best_j] += task.cpu_demand_pct
            proj_mems[best_j] += task.mem_demand_mb
            if record_in_flight:
                self.in_flight.reserve(task, chosen_worker.worker_id)

        peak_cpu = min(100.0, max(proj_cpus) if proj_cpus else 0.0)
        peak_mem_pct = min(
            100.0,
            max((proj_mems[j] / total_mems[j]) * 100.0 for j in range(len(workers)))
            if workers
            else 0.0,
        )
        warning_msg = (
            f"MILP infeasible ({reason}); degraded fallback routed {len(batch)} task(s) "
            f"to lowest-projected-load worker(s) (peak CPU {peak_cpu:.1f}%)."
        )
        logger.warning(
            "milp_degraded_fallback",
            reason=reason,
            batch_size=len(batch),
            projected_peak_cpu=round(peak_cpu, 2),
        )
        return BatchAssignmentResult(
            assignments=assignments,
            meta=SchedulerDecisionMeta(
                scheduler=self.name,
                status="DEGRADED_FALLBACK",
                solver_latency_ms=round(elapsed_ms, 3),
                projected_peak_cpu=round(peak_cpu, 2),
                projected_peak_mem_pct=round(peak_mem_pct, 2),
                degraded=True,
                warning=warning_msg,
            ),
        )

    def assign(
        self,
        batch: Sequence[Task],
        workers: Sequence[Telemetry],
        record_in_flight: bool = True,
    ) -> BatchAssignmentResult:
        """Solve the MILP batch assignment problem within time_limit_ms."""
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

        from app.core.live_stats import live_dispatch_tracker

        num_tasks = len(batch)
        num_workers = len(workers)

        self._rr_tie_break = (self._rr_tie_break + 1) % max(1, num_workers)

        base_cpus: list[float] = []
        base_mems: list[float] = []
        total_mems: list[float] = []
        tie_break_costs: list[float] = []

        cumul_counts = [live_dispatch_tracker.get_worker_cumulative(w.worker_id) for w in workers]
        min_cumul = min(cumul_counts) if cumul_counts else 0

        for j, w in enumerate(workers):
            if_cpu, if_mem, if_cnt = self.in_flight.get_worker_in_flight(w.worker_id, now_mono)
            inflight_count = max(if_cnt, self.in_flight.get_count(w.worker_id))
            inflight_load = max(if_cpu, float(inflight_count) * 15.0)
            inflight_mem = max(if_mem, float(inflight_count) * 128.0)

            queue_len = float(
                getattr(w, "queue_length", 0)
                or getattr(w, "active_task_count", 0)
                or 0
            )
            queue_penalty = min(20.0, queue_len * 5.0)

            rel_cumul = max(0, cumul_counts[j] - min_cumul)
            cumul_penalty = min(20.0, float(rel_cumul) * 5.0)

            # Hard cap checks track true utilization + active in-flight load (no unbounded drift)
            base_cpus.append(float(w.cpu_percent) + inflight_load)
            base_mems.append(float(w.memory_used_mb) + inflight_mem)
            total_mems.append(max(1.0, float(w.memory_total_mb)))

            rr_order = (j - self._rr_tie_break) % num_workers
            tie_break_costs.append(queue_penalty + cumul_penalty + float(rr_order) * 0.01)

        if num_tasks == 0:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            peak_cpu = min(100.0, max(base_cpus))
            peak_mem = min(
                100.0,
                max((base_mems[j] / total_mems[j]) * 100.0 for j in range(num_workers)),
            )
            return BatchAssignmentResult(
                assignments={},
                meta=SchedulerDecisionMeta(
                    scheduler=self.name,
                    status="OPTIMAL",
                    solver_latency_ms=round(elapsed_ms, 3),
                    projected_peak_cpu=round(peak_cpu, 2),
                    projected_peak_mem_pct=round(peak_mem, 2),
                    degraded=False,
                ),
            )

        solver = self._create_solver()
        if solver is None:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            return self._degraded_fallback(
                batch=batch,
                workers=workers,
                base_cpus=base_cpus,
                base_mems=base_mems,
                total_mems=total_mems,
                elapsed_ms=elapsed_ms,
                reason="SOLVER_UNAVAILABLE",
                record_in_flight=record_in_flight,
                tie_break_costs=tie_break_costs,
            )

        solver.SetTimeLimit(int(self.time_limit_ms))

        # Decision variables: X[i][j] in {0, 1}
        x_vars: list[list[Any]] = [
            [solver.IntVar(0, 1, f"x_{i}_{j}") for j in range(num_workers)]
            for i in range(num_tasks)
        ]

        # Continuous minimax variables Z (peak CPU %) and M (peak RAM %)
        z_var: Any = solver.NumVar(0.0, 100.0, "Z")
        m_var: Any = solver.NumVar(0.0, 100.0, "M")

        # Constraint 1: Each task i must be assigned to exactly 1 worker j
        for i in range(num_tasks):
            solver.Add(solver.Sum(x_vars[i]) == 1)

        # Constraints 2, 3, 4, 5 per worker j
        mem_cap_fraction = self.mem_cap_pct / 100.0
        for j in range(num_workers):
            added_cpu_expr = solver.Sum([batch[i].cpu_demand_pct * x_vars[i][j] for i in range(num_tasks)])
            added_mem_expr = solver.Sum([batch[i].mem_demand_mb * x_vars[i][j] for i in range(num_tasks)])

            projected_cpu_expr = base_cpus[j] + added_cpu_expr
            projected_mem_expr = base_mems[j] + added_mem_expr
            mem_limit_mb = mem_cap_fraction * total_mems[j]

            # If a worker is already above cap before this batch, forbid assigning new tasks to it
            # so other healthy workers can still solve feasibly.
            if base_cpus[j] > self.cpu_cap_pct or base_mems[j] > mem_limit_mb:
                for i in range(num_tasks):
                    solver.Add(x_vars[i][j] == 0)
            else:
                solver.Add(projected_cpu_expr <= self.cpu_cap_pct)
                solver.Add(projected_mem_expr <= mem_limit_mb)
                solver.Add(projected_cpu_expr <= z_var)
                solver.Add((projected_mem_expr * (100.0 / total_mems[j])) <= m_var)

        # Objective: minimize Z + 0.001 * peak RAM % + tie-break penalty
        # The tie-break penalty breaks equal-cost ties by fewest cumulative dispatches in current test,
        # then round-robin order, spreading load evenly across all workers under light load.
        tie_break_expr = solver.Sum(
            [
                tie_break_costs[j] * x_vars[i][j]
                for i in range(num_tasks)
                for j in range(num_workers)
            ]
        )
        solver.Minimize(z_var + 0.001 * m_var + tie_break_expr)

        global SOLVER_CALL_COUNT
        SOLVER_CALL_COUNT += 1

        status_code = solver.Solve()
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0

        if status_code not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            return self._degraded_fallback(
                batch=batch,
                workers=workers,
                base_cpus=base_cpus,
                base_mems=base_mems,
                total_mems=total_mems,
                elapsed_ms=elapsed_ms,
                reason="CAPACITY_CAPS_EXCEEDED",
                record_in_flight=record_in_flight,
                tie_break_costs=tie_break_costs,
            )

        assignments: dict[str, str] = {}
        proj_cpus = list(base_cpus)
        proj_mems = list(base_mems)

        for i, task in enumerate(batch):
            assigned_j = 0
            for j in range(num_workers):
                if x_vars[i][j].solution_value() > 0.5:
                    assigned_j = j
                    break
            chosen_worker = workers[assigned_j]
            assignments[task.task_id] = chosen_worker.worker_id
            proj_cpus[assigned_j] += task.cpu_demand_pct
            proj_mems[assigned_j] += task.mem_demand_mb
            if record_in_flight:
                self.in_flight.reserve(task, chosen_worker.worker_id, now_mono)

        peak_cpu = min(100.0, max(proj_cpus))
        peak_mem_pct = min(
            100.0,
            max((proj_mems[j] / total_mems[j]) * 100.0 for j in range(num_workers)),
        )
        status_str = "OPTIMAL" if status_code == pywraplp.Solver.OPTIMAL else "FEASIBLE"

        return BatchAssignmentResult(
            assignments=assignments,
            meta=SchedulerDecisionMeta(
                scheduler=self.name,
                status=status_str,
                solver_latency_ms=round(elapsed_ms, 3),
                projected_peak_cpu=round(peak_cpu, 2),
                projected_peak_mem_pct=round(peak_mem_pct, 2),
                degraded=False,
                warning=None,
            ),
        )

