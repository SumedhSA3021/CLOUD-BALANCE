"""Unit and Integration Tests for Task A2: MILP In-Flight Counter.

Verifies:
1. Per-worker in-flight increment under lock at dispatch time.
2. In-flight decrement on completion and in try/finally on worker error/503.
3. MILP load input incorporates in-flight counters.
4. Concurrent burst of 20 tasks in MILP mode spreads across all 3 workers.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from app.models.schemas import Telemetry
from app.schedulers.base import InFlightTracker


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
async def test_post_tasks_try_finally_decrements_on_error() -> None:
    """Verify in-flight counter decrements even when worker returns 503 on POST /tasks."""
    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _req: httpx.Response(503, json={"status": "rejected_503", "detail": "queue full"})
        )
    )
    cfg = Settings(local_mode=True, seed_demo_workers=False, default_scheduler="ortools_milp")
    app = create_app(settings=cfg, worker_http_client=mock_http)
    await app.state.cluster_state.update_telemetry(make_test_worker("worker-1"))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inflight-503") as client:
        resp = await client.post("/tasks", json={"client_id": "test-client", "task_type": "light"})
        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "rejected_503"
        assert app.state.in_flight_tracker.get_count("worker-1") == 0

    await mock_http.aclose()


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
                headers={"X-Worker-Secret": cfg.worker_secret},
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

        # Submit 20 concurrent tasks via unified pipeline
        async def submit(i: int) -> dict:
            resp = await client.post(
                "/tasks",
                json={"client_id": f"laptop-{i % 3}", "task_type": "heavy", "size": 5000},
            )
            assert resp.status_code == 200
            return resp.json()

        responses = await asyncio.gather(*[submit(i) for i in range(20)])
        assert len(responses) == 20

        # Tally distribution across workers
        distribution: dict[str, int] = {}
        for r in responses:
            wid = r["assigned_worker"]
            distribution[wid] = distribution.get(wid, 0) + 1

        # Must be distributed across ALL 3 workers!
        assert len(distribution) == 3
        for wid in ("worker-1", "worker-2", "worker-3"):
            assert wid in distribution
            # Each worker gets a balanced share (e.g. 4-10 tasks), never 0 and never 20
            assert 4 <= distribution[wid] <= 10

        # After dispatch completion, all in-flight counters return to 0
        for wid in ("worker-1", "worker-2", "worker-3"):
            assert app.state.in_flight_tracker.get_count(wid) == 0
