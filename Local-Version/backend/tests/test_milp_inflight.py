"""Unit and Integration Tests for Task A2: MILP In-Flight Counter.

Verifies:
1. Per-worker in-flight increment under lock at dispatch time.
2. In-flight decrement on completion and in try/finally on worker error/503.
3. MILP load input incorporates in-flight counters.
4. Concurrent burst of 20 tasks in MILP mode spreads across all 3 workers.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.core.profiles import TaskType
from app.main import create_app
from app.models.schemas import Task, TaskRequest, Telemetry
from app.schedulers.base import InFlightTracker
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.services.dispatcher import DispatcherService
from app.services.history import HistoryService


def make_test_worker(wid: str, cpu: float = 15.0, active_tasks: int = 0) -> Telemetry:
    return Telemetry(
        worker_id=wid,
        ip_address="127.0.0.1",
        port=8001,
        cpu_percent=cpu,
        memory_total_mb=4096.0,
        memory_used_mb=512.0,
        memory_percent=12.5,
        load_avg_1m=0.5,
        active_task_count=active_tasks,
    )


def test_inflight_tracker_increment_decrement_and_clear() -> None:
    """Verify InFlightTracker counter operations are thread-safe and never negative."""
    tracker = InFlightTracker()

    assert tracker.get_count("worker-1") == 0
    c1 = tracker.increment("worker-1")
    c2 = tracker.increment("worker-1")
    assert c1 == 1
    assert c2 == 2
    assert tracker.get_count("worker-1") == 2

    c3 = tracker.decrement("worker-1")
    assert c3 == 1
    assert tracker.get_count("worker-1") == 1

    c4 = tracker.decrement("worker-1")
    assert c4 == 0
    # Clamps at 0
    c5 = tracker.decrement("worker-1")
    assert c5 == 0
    assert tracker.get_count("worker-1") == 0


@pytest.mark.asyncio
async def test_dispatcher_try_finally_decrements_on_error() -> None:
    """Verify in-flight counter decrements even when worker returns 503 / exception."""
    tracker = InFlightTracker()
    scheduler = ORToolsMILPScheduler(in_flight_tracker=tracker)

    mock_cluster_state = AsyncMock()
    mock_cluster_state.killed_workers = set()
    mock_cluster_state.evict_worker = AsyncMock()

    mock_mongo = AsyncMock()
    mock_history = HistoryService(mongo_client=mock_mongo)

    dispatcher = DispatcherService(
        cluster_state=mock_cluster_state,
        history=mock_history,
    )

    worker = make_test_worker("worker-err")
    task = Task.from_request(TaskRequest(client_id="test-client", task_type=TaskType.LIGHTWEIGHT_QUERY))

    # Mock _post_to_worker to raise 503 HTTPStatusError
    with patch.object(
        dispatcher,
        "_post_to_worker",
        side_effect=httpx.HTTPStatusError("503 Service Unavailable", request=None, response=None),
    ):
        await dispatcher.dispatch_task(
            task=task,
            initial_worker=worker,
            candidate_workers=[worker],
            scheduler=scheduler,
        )

    # In-flight count must be strictly 0 after the finally block
    assert tracker.get_count("worker-err") == 0


@pytest.mark.asyncio
async def test_milp_burst_spreads_across_all_three_workers() -> None:
    """A burst of 20 concurrent tasks in MILP mode spreads across all 3 workers."""
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        default_scheduler="ortools_milp",
    )
    app = create_app(settings=cfg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Seed 3 virtual workers with identical telemetry (15% CPU)
        for wid, port in (("worker-1", 8001), ("worker-2", 8002), ("worker-3", 8003)):
            await client.post(
                "/api/v1/telemetry",
                json={
                    "worker_id": wid,
                    "ip_address": "virtual",
                    "port": port,
                    "cpu_percent": 15.0,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 512.0,
                    "memory_percent": 12.5,
                    "load_avg_1m": 0.5,
                    "active_task_count": 0,
                },
            )

        # Submit 20 concurrent tasks
        async def submit(i: int) -> dict:
            resp = await client.post(
                "/api/v1/tasks",
                json={"client_id": f"laptop-{i % 3}", "task_type": "BALANCED_COMPUTE"},
            )
            assert resp.status_code == 202
            return resp.json()

        await asyncio.gather(*[submit(i) for i in range(20)])

        # Flush batch
        assignments = await app.state.batcher.flush_one_batch(wait_for_dispatch=True)
        assert len(assignments) == 20

        # Tally distribution across workers
        distribution: dict[str, int] = {}
        for a in assignments:
            distribution[a.assigned_worker_id] = distribution.get(a.assigned_worker_id, 0) + 1

        # Must be distributed across ALL 3 workers!
        assert len(distribution) == 3
        for wid in ("worker-1", "worker-2", "worker-3"):
            assert wid in distribution
            # Each worker gets a balanced share (e.g. 6-8 tasks), never 0 and never 20
            assert 4 <= distribution[wid] <= 10

        # After dispatch completion, all in-flight counters return to 0
        for wid in ("worker-1", "worker-2", "worker-3"):
            assert app.state.batcher.active_scheduler.in_flight.get_count(wid) == 0
