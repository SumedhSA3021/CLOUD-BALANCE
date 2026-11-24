"""Unit and Integration Tests for A3, C1, C2, C3, and C4 Contracts.

Verifies:
- A3: Mode lock and reset hooks (start_test, end_test, is_test_running, 409 on mode change during test).
- C1: Public task endpoint (POST /tasks returning result, assigned_worker, queue_ms, exec_ms, total_ms).
- C2: Test lifecycle (POST /admin/test/start, POST /admin/test/stop, GET /test/status, token auth, one test at a time).
- C3: CSV logger (data/test_log.csv with exact contract columns).
- C4: Summary and stats (data/test_summary.csv, busy_time_stddev as sum of exec_ms, admin stats endpoints).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.logger import (
    TEST_LOG_COLUMNS,
    TEST_LOG_PATH,
    TEST_SUMMARY_COLUMNS,
    TEST_SUMMARY_PATH,
    csv_logger,
    write_test_summary,
)
from app.main import create_app
from app.schedulers.ortools_milp import get_solver_call_count
from app.schedulers.test_hooks import (
    ModeLockedError,
    end_test,
    is_test_running,
    start_test,
)

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "cb-admin-secret-2026")


@pytest.fixture
def app_client() -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://controller-test")


@pytest.mark.asyncio
async def test_a3_mode_lock_and_reset_hooks(app_client: httpx.AsyncClient) -> None:
    """A3: start_test resets counters; mode changes during test raise 409."""
    end_test()
    assert is_test_running() is False

    # Start test in round_robin mode
    start_test(mode="round_robin", test_id="test-a3-1")
    assert is_test_running() is True
    assert get_solver_call_count() == 0

    # Calling start_test again raises ModeLockedError
    with pytest.raises(ModeLockedError):
        start_test(mode="milp")

    # Attempting to change scheduler mode via API returns 409 Conflict
    resp = await app_client.post(
        "/api/v1/control/scheduler",
        json={"scheduler": "ortools_milp"},
    )
    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"].lower()

    # Release lock
    end_test()
    assert is_test_running() is False

    # After end_test, mode change succeeds
    resp_ok = await app_client.post(
        "/api/v1/control/scheduler",
        json={"scheduler": "ortools_milp"},
    )
    assert resp_ok.status_code == 200


@pytest.mark.asyncio
async def test_c2_test_lifecycle_and_auth(app_client: httpx.AsyncClient) -> None:
    """C2: Admin endpoints require Bearer token; GET /test/status is public."""
    end_test()

    # GET /test/status is public
    status_resp = await app_client.get("/test/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["state"] == "idle"

    # POST /admin/test/start without token returns 401
    unauth_resp = await app_client.post(
        "/admin/test/start",
        json={"mode": "round_robin", "duration_s": 10.0, "lambda_per_client": 5.0, "heavy_ratio": 0.2, "seed": 42},
    )
    assert unauth_resp.status_code == 401

    # POST /admin/test/start with valid Bearer token succeeds and arms the test
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    start_resp = await app_client.post(
        "/admin/test/start",
        headers=headers,
        json={"mode": "round_robin", "duration_s": 10.0, "lambda_per_client": 5.0, "heavy_ratio": 0.2, "seed": 42},
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    assert start_data["state"] == "armed"
    assert start_data["test_id"] is not None
    assert start_data["start_at"] is not None
    assert is_test_running() is True

    # Second start while active returns 409 (one test at a time)
    conflict_resp = await app_client.post(
        "/admin/test/start",
        headers=headers,
        json={"mode": "milp", "duration_s": 10.0, "lambda_per_client": 5.0, "heavy_ratio": 0.2, "seed": 42},
    )
    assert conflict_resp.status_code == 409

    # Stop test
    stop_resp = await app_client.post("/admin/test/stop", headers=headers)
    assert stop_resp.status_code == 200
    assert is_test_running() is False


@pytest.mark.asyncio
async def test_c1_task_endpoint_and_c3_csv_logging(app_client: httpx.AsyncClient) -> None:
    """C1 & C3: POST /tasks returns contract response and appends exact columns to test_log.csv."""
    end_test()

    task_payload = {
        "client_id": "laptop-alpha",
        "task_type": "light",
        "size": 50,
        "sent_at": 1700000000.5,
    }

    resp = await app_client.post("/tasks", json=task_payload)
    assert resp.status_code == 200
    data = resp.json()

    # Exact Task response contract: result, assigned_worker, queue_ms, exec_ms, total_ms
    assert "result" in data
    assert "assigned_worker" in data
    assert data["assigned_worker"] in ("worker-1", "worker-2", "worker-3")
    assert "queue_ms" in data
    assert "exec_ms" in data
    assert "total_ms" in data
    assert data["total_ms"] >= 0.0

    # Verify CSV logger captured the entry with exact columns
    csv_logger.flush()
    assert TEST_LOG_PATH.exists()

    with open(TEST_LOG_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == TEST_LOG_COLUMNS
        rows = list(reader)
        assert len(rows) >= 1

        last_row = rows[-1]
        assert last_row["client_id"] == "laptop-alpha"
        assert last_row["task_type"] == "light"
        assert last_row["assigned_worker"] in ("worker-1", "worker-2", "worker-3")
        assert last_row["status"] in ("ok", "timeout", "rejected_503", "error")
        assert "scheduler_used" in last_row


def test_c4_summary_computation_busy_time_stddev(tmp_path: Path) -> None:
    """C4: Verify busy_time_stddev is the std-dev of per-worker busy time (exec_ms sum), NOT task count."""
    test_id = "test-c4-verify"
    log_file = tmp_path / "test_log.csv"
    summary_file = tmp_path / "test_summary.csv"

    # Write synthetic log rows with known exec_ms per worker
    # worker-1: 100ms, worker-2: 200ms, worker-3: 300ms
    # Sums: [100.0, 200.0, 300.0]
    # Population stddev of [100, 200, 300] = sqrt((( -100)^2 + 0^2 + 100^2)/3) = sqrt(20000/3) = 81.65
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEST_LOG_COLUMNS)
        writer.writeheader()
        writer.writerow({
            "test_id": test_id, "mode": "round_robin", "seed": 42, "duration_s": 10.0,
            "lambda_per_client": 5.0, "heavy_ratio": 0.2, "client_id": "c1", "task_id": "t1",
            "task_type": "heavy", "sent_at": 100.0, "scheduler_used": "round_robin", "dispatch_seq": 1,
            "assigned_worker": "worker-1", "worker_inflight_at_dispatch": 1, "worker_cpu_pct_at_dispatch": 10.0,
            "queue_ms": 2.0, "exec_ms": 100.0, "total_ms": 102.0, "status": "ok",
        })
        writer.writerow({
            "test_id": test_id, "mode": "round_robin", "seed": 42, "duration_s": 10.0,
            "lambda_per_client": 5.0, "heavy_ratio": 0.2, "client_id": "c2", "task_id": "t2",
            "task_type": "heavy", "sent_at": 100.0, "scheduler_used": "round_robin", "dispatch_seq": 2,
            "assigned_worker": "worker-2", "worker_inflight_at_dispatch": 1, "worker_cpu_pct_at_dispatch": 15.0,
            "queue_ms": 3.0, "exec_ms": 200.0, "total_ms": 203.0, "status": "ok",
        })
        writer.writerow({
            "test_id": test_id, "mode": "round_robin", "seed": 42, "duration_s": 10.0,
            "lambda_per_client": 5.0, "heavy_ratio": 0.2, "client_id": "c3", "task_id": "t3",
            "task_type": "heavy", "sent_at": 100.0, "scheduler_used": "round_robin", "dispatch_seq": 3,
            "assigned_worker": "worker-3", "worker_inflight_at_dispatch": 1, "worker_cpu_pct_at_dispatch": 12.0,
            "queue_ms": 1.0, "exec_ms": 300.0, "total_ms": 301.0, "status": "ok",
        })

    summary = write_test_summary(
        test_id=test_id,
        mode="round_robin",
        seed=42,
        duration_s=10.0,
        lambda_per_client=5.0,
        heavy_ratio=0.2,
        log_path=log_file,
        summary_path=summary_file,
    )

    assert summary["test_id"] == test_id
    assert summary["requests"] == 3
    assert summary["failed"] == 0
    assert summary["worker1_busy_ms"] == 100.0
    assert summary["worker2_busy_ms"] == 200.0
    assert summary["worker3_busy_ms"] == 300.0
    assert summary["busy_time_stddev"] == 81.65
    assert summary["throughput_rps"] == 0.3  # 3 / 10s


@pytest.mark.asyncio
async def test_c4_admin_stats_endpoints(app_client: httpx.AsyncClient) -> None:
    """C4: Endpoints GET /admin/stats/summary, GET /admin/stats/download, POST /admin/stats/reset."""
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

    # Reset
    reset_resp = await app_client.post("/admin/stats/reset", headers=headers)
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "reset"

    # Summary
    summary_resp = await app_client.get("/admin/stats/summary", headers=headers)
    assert summary_resp.status_code == 200
    assert isinstance(summary_resp.json(), list)

    # Download
    download_resp = await app_client.get("/admin/stats/download", headers=headers)
    assert download_resp.status_code == 200
    assert "text/csv" in download_resp.headers.get("content-type", "")
