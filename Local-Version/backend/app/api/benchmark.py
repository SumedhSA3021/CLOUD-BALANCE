"""Benchmark Runs API (`GET /api/v1/benchmark/runs` and `POST /api/v1/benchmark/run`)."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request

from app.core.profiles import TaskType
from app.core.security import verify_api_key
from app.models.schemas import (
    BenchmarkRun,
    SchedulerBenchmarkMetrics,
    Task,
    TaskRequest,
    Telemetry,
)
from app.schedulers.base import BaseScheduler, InFlightTracker
from app.schedulers.least_connections import LeastConnectionsScheduler
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.schedulers.round_robin import RoundRobinScheduler
from app.services.history import HistoryService

router = APIRouter(prefix="/api/v1/benchmark", tags=["benchmark"])


def run_seeded_benchmark_simulation(
    seed: int = 42,
    num_batches: int = 18,
    batch_size: int = 4,
) -> BenchmarkRun:
    """Replay an identical seeded multi-client task trace across all 3 schedulers.

    Evaluates:
      - CPU std-dev across workers over time
      - Peak CPU % and Peak RAM %
      - Capacity violations (>85% CPU, >90% RAM)
      - Mean & p95 completion latency
      - Solver latency & throughput
    """
    import random

    rng = random.Random(seed)
    clients = [
        ("laptop-alpha", [TaskType.CPU_INTENSIVE, TaskType.CPU_INTENSIVE, TaskType.BALANCED_COMPUTE]),
        ("laptop-beta", [TaskType.MEMORY_INTENSIVE, TaskType.MEMORY_INTENSIVE, TaskType.BALANCED_COMPUTE]),
        ("laptop-gamma", [TaskType.CPU_INTENSIVE, TaskType.LIGHTWEIGHT_QUERY, TaskType.BALANCED_COMPUTE]),
    ]

    # Pre-generate identical batches of tasks
    batches: list[list[Task]] = []
    for _ in range(num_batches):
        batch: list[Task] = []
        for _ in range(batch_size):
            cid, pool = rng.choice(clients)
            t_type = rng.choice(pool)
            batch.append(Task.from_request(TaskRequest(client_id=cid, task_type=t_type)))
        batches.append(batch)

    total_tasks = num_batches * batch_size
    results: dict[str, SchedulerBenchmarkMetrics] = {}

    scheduler_instances: list[tuple[str, BaseScheduler]] = [
        ("ortools_milp", ORToolsMILPScheduler(in_flight_tracker=InFlightTracker())),
        ("round_robin", RoundRobinScheduler(in_flight_tracker=InFlightTracker())),
        ("least_connections", LeastConnectionsScheduler(in_flight_tracker=InFlightTracker())),
    ]

    for sched_name, scheduler in scheduler_instances:

        # Initial heterogeneous worker baseline
        worker_cpus = {"worker-1": 24.0, "worker-2": 18.0, "worker-3": 12.0}
        worker_mems = {"worker-1": 900.0, "worker-2": 700.0, "worker-3": 600.0}
        worker_totals = {"worker-1": 4096.0, "worker-2": 4096.0, "worker-3": 4096.0}
        worker_tasks = {"worker-1": 1, "worker-2": 1, "worker-3": 0}
        assigned_counts = {"worker-1": 0, "worker-2": 0, "worker-3": 0}

        stddev_series: list[float] = []
        peak_cpu_series: list[float] = []
        solver_latencies: list[float] = []
        completion_latencies: list[float] = []
        cpu_violations = 0
        mem_violations = 0
        degraded_count = 0
        peak_cpu_overall = 0.0
        peak_mem_overall = 0.0

        for batch in batches:
            # Decay existing worker utilization each step (simulating task completions)
            for wid in worker_cpus:
                worker_cpus[wid] = max(8.0, round(worker_cpus[wid] * 0.45, 2))
                worker_mems[wid] = max(480.0, round(worker_mems[wid] * 0.55, 2))
                worker_tasks[wid] = max(0, worker_tasks[wid] - 1)

            telemetry_list = [
                Telemetry(
                    worker_id=wid,
                    ip_address="10.128.0.10",
                    port=8001,
                    timestamp=datetime.now(UTC),
                    cpu_percent=min(100.0, worker_cpus[wid]),
                    memory_total_mb=worker_totals[wid],
                    memory_used_mb=min(worker_totals[wid], worker_mems[wid]),
                    memory_percent=min(100.0, round((worker_mems[wid] / worker_totals[wid]) * 100.0, 2)),
                    load_avg_1m=round(worker_cpus[wid] / 25.0, 2),
                    active_task_count=worker_tasks[wid],
                )
                for wid in ("worker-1", "worker-2", "worker-3")
            ]

            res = scheduler.assign(batch, telemetry_list, record_in_flight=False)
            solver_latencies.append(res.meta.solver_latency_ms)
            if res.meta.degraded:
                degraded_count += len(batch)

            for task in batch:
                chosen = res.assignments[task.task_id]
                assigned_counts[chosen] += 1
                worker_cpus[chosen] += task.cpu_demand_pct
                worker_mems[chosen] += task.mem_demand_mb
                worker_tasks[chosen] += 1

                # Contention slowdown when worker is heavily loaded
                overload_factor = 1.0
                if worker_cpus[chosen] > 70.0:
                    overload_factor += ((worker_cpus[chosen] - 70.0) ** 1.35) * 0.03
                mem_pct_now = (worker_mems[chosen] / worker_totals[chosen]) * 100.0
                if mem_pct_now > 80.0:
                    overload_factor += (mem_pct_now - 80.0) * 0.04
                completion_latencies.append(
                    round(task.duration_sec * 100.0 * overload_factor + res.meta.solver_latency_ms, 2)
                )

            step_cpus = list(worker_cpus.values())
            step_mem_pcts = [
                (worker_mems[w] / worker_totals[w]) * 100.0 for w in ("worker-1", "worker-2", "worker-3")
            ]
            for c_val in step_cpus:
                if c_val > 85.0:
                    cpu_violations += 1
            for m_val in step_mem_pcts:
                if m_val > 90.0:
                    mem_violations += 1

            step_std = round(statistics.pstdev(step_cpus), 2)
            step_peak_cpu = round(min(100.0, max(step_cpus)), 2)
            step_peak_mem = round(min(100.0, max(step_mem_pcts)), 2)
            stddev_series.append(step_std)
            peak_cpu_series.append(step_peak_cpu)
            peak_cpu_overall = max(peak_cpu_overall, step_peak_cpu)
            peak_mem_overall = max(peak_mem_overall, step_peak_mem)

        sorted_comp = sorted(completion_latencies)
        p95_idx = min(len(sorted_comp) - 1, int(len(sorted_comp) * 0.95))
        sorted_solv = sorted(solver_latencies)
        p95_solv_idx = min(len(sorted_solv) - 1, int(len(sorted_solv) * 0.95))

        sim_duration = round(num_batches * 0.25, 2)
        results[sched_name] = SchedulerBenchmarkMetrics(
            scheduler=sched_name,
            total_tasks=total_tasks,
            completed_tasks=total_tasks,
            degraded_assignments=degraded_count,
            cpu_stddev_mean=round(statistics.mean(stddev_series), 2),
            cpu_stddev_max=round(max(stddev_series), 2),
            peak_cpu_pct=round(peak_cpu_overall, 2),
            peak_mem_pct=round(peak_mem_overall, 2),
            cpu_cap_violations=cpu_violations,
            mem_cap_violations=mem_violations,
            total_cap_violations=cpu_violations + mem_violations,
            mean_completion_latency_ms=round(statistics.mean(completion_latencies), 2),
            p95_completion_latency_ms=round(sorted_comp[p95_idx], 2),
            mean_solver_latency_ms=round(statistics.mean(solver_latencies), 3),
            p95_solver_latency_ms=round(sorted_solv[p95_solv_idx], 3),
            throughput_tasks_per_sec=round(total_tasks / max(0.1, sim_duration), 2),
            time_series_cpu_stddev=stddev_series,
            time_series_peak_cpu=peak_cpu_series,
            worker_assignment_counts=assigned_counts,
        )

    lines = [
        (
            "| Scheduler | Mean CPU StdDev (%) | Peak CPU (%) | Peak RAM (%) "
            "| Cap Violations | Mean Latency (ms) | P95 Latency (ms) | Mean Solver (ms) |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s_name in ("ortools_milp", "least_connections", "round_robin"):
        m = results[s_name]
        lines.append(
            f"| `{s_name}` | {m.cpu_stddev_mean:.2f} | {m.peak_cpu_pct:.1f} | "
            f"{m.peak_mem_pct:.1f} | {m.total_cap_violations} | "
            f"{m.mean_completion_latency_ms:.1f} | {m.p95_completion_latency_ms:.1f} | "
            f"{m.mean_solver_latency_ms:.3f} |"
        )

    return BenchmarkRun(
        seed=seed,
        total_tasks=total_tasks,
        duration_sec=round(num_batches * 0.25, 2),
        results=results,
        markdown_table="\n".join(lines),
    )


@router.get("/runs", response_model=list[BenchmarkRun])
async def list_benchmark_runs(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[BenchmarkRun]:
    """Return stored benchmark runs; automatically generates a default seeded run if none exist yet."""
    history: HistoryService = request.app.state.history
    runs = await history.get_benchmark_runs(limit=limit)
    if not runs:
        default_run = run_seeded_benchmark_simulation(seed=42)
        await history.record_benchmark_run(default_run)
        runs = [default_run]
    return runs


@router.post("/run", response_model=BenchmarkRun)
async def trigger_benchmark_run(
    request: Request,
    seed: int = Query(default=42),
    num_batches: int = Query(default=18, ge=4, le=100),
    _api_key: str = Depends(verify_api_key),
) -> BenchmarkRun:
    """Trigger a new seeded 3-scheduler comparison benchmark and persist the result."""
    history: HistoryService = request.app.state.history
    run = run_seeded_benchmark_simulation(seed=seed, num_batches=num_batches)
    await history.record_benchmark_run(run)
    return run
