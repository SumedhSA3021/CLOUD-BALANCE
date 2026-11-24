"""Automated pytest test suite verifying:
1. RR test: 3 clients send 30+ tasks concurrently in round_robin mode; sort rows by dispatch_seq; assert strict w1,w2,w3 cycle.
2. Assert solver call count == 0 in the RR test and > 0 in the MILP test.
3. Assert start_test resets rr_counter and in-flight counters, and a mode change during a running test is rejected with 409.
"""

from __future__ import annotations

import asyncio
import csv
import time
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.core.config import Settings
from app.core.logger import TEST_LOG_PATH, csv_logger
from app.main import create_app
from app.schedulers.ortools_milp import get_solver_call_count, reset_solver_call_count
from app.schedulers.test_hooks import (
    ModeLockedError,
    end_test,
    is_test_running,
    start_test,
)


@pytest.fixture(autouse=True)
def intercept_worker_http_calls():
    """Intercept outgoing HTTP calls to worker nodes (:8001..:8003/execute).

    Allows concurrent tests to run instantly without requiring background worker processes.
    """
    orig_post = httpx.AsyncClient.post

    async def mock_post(self: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:
        url_str = str(url)
        if any(port in url_str for port in (":8001", ":8002", ":8003", "/execute")):
            return httpx.Response(
                status_code=200,
                json={
                    "task_id": "mock-task-id",
                    "worker_id": "mock-worker",
                    "status": "COMPLETED",
                    "execution_ms": 1.5,
                    "queue_ms": 0.5,
                    "result": {"status": "ok", "cgpa": 9.0},
                },
                request=httpx.Request("POST", url_str),
            )
        return await orig_post(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "post", new=mock_post):
        yield


@pytest.fixture
def app_instance():
    """Create a test controller application instance in local_mode."""
    end_test()
    cfg = Settings(local_mode=True, seed_demo_workers=False)
    app = create_app(settings=cfg)
    return app


@pytest.fixture
async def test_client(app_instance):
    """Async test client using ASGITransport."""
    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(transport=transport, base_url="http://testcontroller") as client:
        yield client
    end_test()


@pytest.mark.asyncio
async def test_1_round_robin_concurrent_strict_cycle(app_instance, test_client: httpx.AsyncClient):
    """Requirement 1: 3 clients send 30+ tasks concurrently in round_robin mode;

    sort rows by dispatch_seq; assert a strict w1,w2,w3 cycle.
    """
    end_test()
    reset_solver_call_count()
    assert get_solver_call_count() == 0

    # Initialize test in round_robin mode via start_test hook
    test_id = "test-rr-strict-36"
    start_test(
        mode="round_robin",
        redis_client=app_instance.state.redis_client,
        in_flight_tracker=app_instance.state.in_flight_tracker,
        test_id=test_id,
        metadata={"seed": 42, "duration_s": 30.0, "lambda_per_client": 5.0, "heavy_ratio": 0.2},
    )

    # 3 distinct clients (laptop-1, laptop-2, laptop-3) sending 36 tasks concurrently (12 each)
    total_tasks = 36
    clients = ["laptop-1", "laptop-2", "laptop-3"]

    async def send_task(idx: int) -> dict[str, Any]:
        c_id = clients[idx % 3]
        resp = await test_client.post(
            "/tasks",
            json={
                "client_id": c_id,
                "task_type": "light",
                "sent_at": time.time(),
            },
        )
        assert resp.status_code == 200, f"Task {idx} failed with {resp.status_code}: {resp.text}"
        return resp.json()

    # Fire all 36 requests simultaneously
    responses = await asyncio.gather(*[send_task(i) for i in range(total_tasks)])

    # Flush CSV logger so rows are flushed to disk
    csv_logger.flush()

    # Verify all returned responses have valid assigned workers and sequence
    assert len(responses) == total_tasks

    # Sort responses by dispatch_seq
    sorted_responses = sorted(responses, key=lambda r: int(r["dispatch_seq"]))

    # Verify sequence numbers are strictly 1..36
    seqs = [int(r["dispatch_seq"]) for r in sorted_responses]
    assert seqs == list(range(1, total_tasks + 1)), f"Sequences not consecutive: {seqs}"

    # Verify assigned workers strictly follow w1, w2, w3 cyclic order
    expected_cycle = ["worker-1", "worker-2", "worker-3"] * (total_tasks // 3)
    actual_cycle = [r["assigned_worker"] for r in sorted_responses]
    assert actual_cycle == expected_cycle, f"Worker assignments diverged from strict RR cycle: {actual_cycle}"

    # Also verify CSV log rows directly from data/test_log.csv
    if TEST_LOG_PATH.exists():
        with open(TEST_LOG_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            test_rows = [r for r in reader if r.get("test_id") == test_id]
        if test_rows:
            sorted_csv_rows = sorted(test_rows, key=lambda r: int(r["dispatch_seq"]))
            csv_workers = [r["assigned_worker"] for r in sorted_csv_rows]
            assert csv_workers == expected_cycle

    # Requirement 2 check for RR: solver_call_count must be strictly 0
    assert get_solver_call_count() == 0, "MILP solver was called during round_robin mode!"
    end_test()


@pytest.mark.asyncio
async def test_2_solver_call_count_zero_in_rr_and_positive_in_milp(app_instance, test_client: httpx.AsyncClient):
    """Requirement 2: Assert solver call count == 0 in the RR test and > 0 in the MILP test."""
    end_test()
    reset_solver_call_count()
    assert get_solver_call_count() == 0

    # Part A: Round Robin test - solver must NOT be called
    start_test(
        mode="round_robin",
        redis_client=app_instance.state.redis_client,
        in_flight_tracker=app_instance.state.in_flight_tracker,
        test_id="test-rr-zero-calls",
    )
    for i in range(6):
        resp = await test_client.post(
            "/tasks",
            json={"client_id": f"client-{i}", "task_type": "light"},
        )
        assert resp.status_code == 200

    assert get_solver_call_count() == 0, f"Expected 0 solver calls in RR, got {get_solver_call_count()}"
    end_test()

    # Part B: MILP test - solver MUST be invoked
    reset_solver_call_count()
    assert get_solver_call_count() == 0

    start_test(
        mode="milp",
        redis_client=app_instance.state.redis_client,
        in_flight_tracker=app_instance.state.in_flight_tracker,
        test_id="test-milp-positive-calls",
    )

    # Submit task under MILP mode
    milp_resp = await test_client.post(
        "/tasks",
        json={"client_id": "client-milp-1", "task_type": "heavy"},
    )
    assert milp_resp.status_code == 200

    # Assert solver was invoked (solver_call_count > 0)
    solver_calls = get_solver_call_count()
    assert solver_calls > 0, f"Expected solver_call_count > 0 in MILP mode, got {solver_calls}"
    end_test()


@pytest.mark.asyncio
async def test_3_start_test_resets_counters_and_mode_change_409(app_instance, test_client: httpx.AsyncClient):
    """Requirement 3: Assert start_test resets rr_counter and in-flight counters,

    and a mode change during a running test is rejected with 409.
    """
    end_test()
    redis_client = app_instance.state.redis_client
    in_flight_tracker = app_instance.state.in_flight_tracker

    # 1. Dirty the counters beforehand
    await redis_client.set("rr_counter", "45")
    in_flight_tracker.increment("worker-1")
    in_flight_tracker.increment("worker-2")
    await redis_client.set("inflight:worker-1", "3")
    await redis_client.set("inflight:worker-2", "2")

    # Verify they are dirty
    assert await redis_client.get("rr_counter") == "45"
    assert in_flight_tracker.get_count("worker-1") > 0

    # 2. Call start_test hook
    start_test(
        mode="round_robin",
        redis_client=redis_client,
        in_flight_tracker=in_flight_tracker,
        test_id="test-reset-validation",
    )

    # Allow async redis reset to finish
    await asyncio.sleep(0.05)

    # Assert rr_counter is reset to 0 in Redis
    rr_val = await redis_client.get("rr_counter")
    assert rr_val in ("0", 0), f"rr_counter was not reset to 0: {rr_val}"

    # Assert in-flight counters are reset to 0
    for w in ("worker-1", "worker-2", "worker-3"):
        assert in_flight_tracker.get_count(w) == 0, f"InFlightTracker for {w} was not zeroed"
        w_inf = await redis_client.get(f"inflight:{w}")
        assert w_inf in ("0", 0, None), f"Redis inflight for {w} was not zeroed: {w_inf}"

    # Assert solver call count is reset to 0
    assert get_solver_call_count() == 0

    # Assert test is active
    assert is_test_running() is True

    # 3. Attempt a mode change via API while test is running
    # Must be rejected with HTTP 409 Conflict
    conflict_resp = await test_client.post(
        "/api/v1/control/scheduler",
        json={"scheduler": "ortools_milp"},
    )
    assert conflict_resp.status_code == 409, (
        f"Expected 409 Conflict when changing mode during running test, got {conflict_resp.status_code}"
    )
    error_detail = conflict_resp.json().get("detail", "").lower()
    assert "locked" in error_detail or "running" in error_detail

    # 4. End the test and verify mode change succeeds
    end_test()
    assert is_test_running() is False

    ok_resp = await test_client.post(
        "/api/v1/control/scheduler",
        json={"scheduler": "ortools_milp"},
    )
    assert ok_resp.status_code == 200, f"Expected 200 after test ended, got {ok_resp.status_code}"
