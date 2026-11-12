"""Comprehensive Unit Tests for OR-Tools MILP, Round Robin, and Least Connections Schedulers."""

from __future__ import annotations

import statistics

from app.core.profiles import TaskType
from app.models.schemas import Task, TaskRequest, Telemetry
from app.schedulers.base import InFlightTracker
from app.schedulers.least_connections import LeastConnectionsScheduler
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.schedulers.round_robin import RoundRobinScheduler


def make_worker(
    worker_id: str,
    cpu_pct: float = 10.0,
    mem_used_mb: float = 512.0,
    mem_total_mb: float = 4096.0,
    active_tasks: int = 0,
) -> Telemetry:
    """Helper to construct a live worker Telemetry snapshot."""
    return Telemetry(
        worker_id=worker_id,
        ip_address="127.0.0.1",
        port=8001,
        cpu_percent=cpu_pct,
        memory_total_mb=mem_total_mb,
        memory_used_mb=mem_used_mb,
        memory_percent=round((mem_used_mb / mem_total_mb) * 100.0, 2),
        load_avg_1m=cpu_pct / 25.0,
        active_task_count=active_tasks,
    )


def make_task(task_type: TaskType, client_id: str = "laptop-1") -> Task:
    """Helper to construct an internal Task from a TaskType."""
    return Task.from_request(TaskRequest(client_id=client_id, task_type=task_type))


def test_milp_single_assignment_and_caps_respected() -> None:
    """Every task in a batch must be assigned to exactly 1 worker and respect 85% CPU / 90% RAM caps."""
    scheduler = ORToolsMILPScheduler(time_limit_ms=50)
    workers = [
        make_worker("worker-1", cpu_pct=20.0, mem_used_mb=512.0),
        make_worker("worker-2", cpu_pct=25.0, mem_used_mb=512.0),
        make_worker("worker-3", cpu_pct=15.0, mem_used_mb=512.0),
    ]
    batch = [
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),
        make_task(TaskType.BALANCED_COMPUTE, "laptop-a"),
        make_task(TaskType.MEMORY_INTENSIVE, "laptop-b"),
        make_task(TaskType.LIGHTWEIGHT_QUERY, "laptop-c"),
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),
    ]

    assignments, meta = scheduler.assign(batch, workers)

    # Single-assignment holds: every task ID is in assignments and points to a valid worker
    assert len(assignments) == len(batch)
    valid_worker_ids = {w.worker_id for w in workers}
    for task in batch:
        assert task.task_id in assignments
        assert assignments[task.task_id] in valid_worker_ids

    # Caps respected when feasible
    assert meta.degraded is False
    assert meta.status in ("OPTIMAL", "FEASIBLE")
    assert meta.projected_peak_cpu <= 85.0
    assert meta.projected_peak_mem_pct <= 90.0


def test_milp_beats_round_robin_on_skewed_loads() -> None:
    """Under skewed initial load and heterogeneous tasks, MILP achieves strictly lower peak CPU and std-dev than RR."""
    workers = [
        make_worker("worker-hot", cpu_pct=70.0, mem_used_mb=1024.0, active_tasks=3),
        make_worker("worker-warm", cpu_pct=45.0, mem_used_mb=1024.0, active_tasks=2),
        make_worker("worker-cold", cpu_pct=10.0, mem_used_mb=512.0, active_tasks=0),
    ]
    batch = [
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),  # 35% CPU
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),  # 35% CPU
        make_task(TaskType.BALANCED_COMPUTE, "laptop-b"),  # 25% CPU
    ]

    milp = ORToolsMILPScheduler(in_flight_tracker=InFlightTracker())
    rr = RoundRobinScheduler(in_flight_tracker=InFlightTracker())

    milp_assign, milp_meta = milp.assign(batch, workers, record_in_flight=False)
    rr_assign, rr_meta = rr.assign(batch, workers, record_in_flight=False)

    # MILP must not assign heavy CPU tasks to worker-hot (already at 70% CPU)
    assert milp_assign[batch[0].task_id] != "worker-hot"
    assert milp_assign[batch[1].task_id] != "worker-hot"
    assert milp_meta.degraded is False
    assert milp_meta.projected_peak_cpu <= 85.0

    # Round Robin blindly assigns task 0 to worker-hot -> 70 + 35 = 105% (capped at 100%)
    assert rr_meta.projected_peak_cpu > milp_meta.projected_peak_cpu

    # Compare post-assignment CPU std-dev across the 3 workers
    def compute_post_cpus(assign_map: dict[str, str]) -> list[float]:
        cpus = {w.worker_id: w.cpu_percent for w in workers}
        for t in batch:
            cpus[assign_map[t.task_id]] += t.cpu_demand_pct
        return list(cpus.values())

    milp_stddev = statistics.pstdev(compute_post_cpus(milp_assign))
    rr_stddev = statistics.pstdev(compute_post_cpus(rr_assign))
    assert milp_stddev < rr_stddev


def test_milp_respects_memory_cap_when_cpu_is_low() -> None:
    """Worker with low CPU (10%) but high memory (3400/4096 MB = 83%) cannot take a 1024MB MEMORY_INTENSIVE task."""
    workers = [
        make_worker("worker-mem-full", cpu_pct=10.0, mem_used_mb=3400.0, mem_total_mb=4096.0),
        make_worker("worker-mem-free", cpu_pct=35.0, mem_used_mb=512.0, mem_total_mb=4096.0),
    ]
    batch = [make_task(TaskType.MEMORY_INTENSIVE, "laptop-b")]  # 1024MB demand

    milp = ORToolsMILPScheduler()
    assignments, meta = milp.assign(batch, workers)

    # 3400 + 1024 = 4424 > 0.90 * 4096 (3686.4), so MILP must pick worker-mem-free
    assert assignments[batch[0].task_id] == "worker-mem-free"
    assert meta.degraded is False


def test_zero_workers_and_single_worker_and_empty_batch() -> None:
    """Verify edge cases: 0 workers, 1 worker, and 0 tasks across all 3 schedulers."""
    batch = [make_task(TaskType.LIGHTWEIGHT_QUERY), make_task(TaskType.BALANCED_COMPUTE)]
    single_worker = [make_worker("worker-solo", cpu_pct=15.0)]

    for sched_cls in (ORToolsMILPScheduler, RoundRobinScheduler, LeastConnectionsScheduler):
        sched = sched_cls()

        # 0 workers
        res_empty_w = sched.assign(batch, [])
        assert res_empty_w.assignments == {}
        assert res_empty_w.meta.status == "NO_WORKERS"
        assert res_empty_w.meta.degraded is True

        # 1 worker
        res_single = sched.assign(batch, single_worker, record_in_flight=False)
        assert len(res_single.assignments) == 2
        for tid in res_single.assignments:
            assert res_single.assignments[tid] == "worker-solo"

        # Empty batch
        res_no_tasks = sched.assign([], single_worker, record_in_flight=False)
        assert res_no_tasks.assignments == {}
        assert res_no_tasks.meta.degraded is False


def test_milp_infeasible_batch_triggers_degraded_fallback() -> None:
    """When a batch exceeds cluster 85% CPU cap, MILP triggers degraded fallback and balances load."""
    workers = [
        make_worker("worker-1", cpu_pct=60.0),
        make_worker("worker-2", cpu_pct=65.0),
    ]
    # 3 CPU_INTENSIVE tasks (3 * 35% = 105% additional CPU on top of 125% existing -> >85% per worker)
    batch = [
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),
        make_task(TaskType.CPU_INTENSIVE, "laptop-a"),
    ]

    milp = ORToolsMILPScheduler()
    assignments, meta = milp.assign(batch, workers)

    assert len(assignments) == 3
    assert meta.degraded is True
    assert meta.status == "DEGRADED_FALLBACK"
    assert meta.warning is not None
    assert "MILP infeasible" in meta.warning
    # Both workers should be used rather than piling all 3 onto one worker
    assert set(assignments.values()) == {"worker-1", "worker-2"}


def test_in_flight_reservations_prevent_consecutive_batch_piling() -> None:
    """Consecutive batches before telemetry updates must account for in-flight reservations with decay."""
    tracker = InFlightTracker()
    milp = ORToolsMILPScheduler(in_flight_tracker=tracker)

    # All 3 workers report identical stale telemetry (10% CPU)
    workers = [
        make_worker("worker-1", cpu_pct=10.0),
        make_worker("worker-2", cpu_pct=10.0),
        make_worker("worker-3", cpu_pct=10.0),
    ]

    # Send 3 consecutive single-task batches without changing worker telemetry
    chosen_workers: list[str] = []
    for _ in range(3):
        t = make_task(TaskType.CPU_INTENSIVE)
        res = milp.assign([t], workers, record_in_flight=True)
        chosen_workers.append(res.assignments[t.task_id])

    # Because in-flight reservations are tracked, the 3 tasks must spread across all 3 workers!
    assert set(chosen_workers) == {"worker-1", "worker-2", "worker-3"}

    # Verify decay factor calculation
    t_decay = make_task(TaskType.BALANCED_COMPUTE)
    tracker.clear()
    res_obj = tracker.reserve(t_decay, "worker-1", now_mono=100.0)
    assert res_obj.decay_factor(100.0) == 1.0
    assert 0.49 <= res_obj.decay_factor(101.5) <= 0.51
    assert res_obj.decay_factor(105.0) == 0.0

    # Release reservation explicitly
    tracker.release(t_decay.task_id)
    if_cpu, if_mem, if_cnt = tracker.get_worker_in_flight("worker-1", now_mono=100.5)
    assert if_cpu == 0.0
    assert if_mem == 0.0
    assert if_cnt == 0


def test_least_connections_scheduler_uses_active_plus_in_flight() -> None:
    """LeastConnectionsScheduler routes to minimum (active_task_count + in_flight_count)."""
    tracker = InFlightTracker()
    lc = LeastConnectionsScheduler(in_flight_tracker=tracker)
    workers = [
        make_worker("worker-busy", cpu_pct=20.0, active_tasks=4),
        make_worker("worker-idle", cpu_pct=50.0, active_tasks=0),
    ]
    batch = [
        make_task(TaskType.LIGHTWEIGHT_QUERY),
        make_task(TaskType.LIGHTWEIGHT_QUERY),
    ]
    assignments, meta = lc.assign(batch, workers, record_in_flight=True)
    assert assignments[batch[0].task_id] == "worker-idle"
    assert assignments[batch[1].task_id] == "worker-idle"
    assert meta.degraded is False

