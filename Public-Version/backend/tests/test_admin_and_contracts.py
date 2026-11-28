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

import httpx
import pytest

from app.core.config import get_settings
from app.core.logger import (
    TEST_LOG_COLUMNS,
    TEST_LOG_PATH,
    TEST_SUMMARY_COLUMNS,
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


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


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
    headers = _admin_headers()
    resp = await app_client.post(
        "/api/v1/control/scheduler",
        headers=headers,
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
        headers=headers,
        json={"scheduler": "ortools_milp"},
    )
    assert resp_ok.status_code == 200


@pytest.mark.asyncio
async def test_c2_test_lifecycle_and_auth(app_client: httpx.AsyncClient) -> None:
    """C2: Admin endpoints require Bearer token; GET /test/status is public."""
    end_test()

    # GET /test/status is public; legacy /admin/test/status alias is removed
    status_resp = await app_client.get("/test/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["state"] == "idle"
    removed_admin_status = await app_client.get("/admin/test/status")
    assert removed_admin_status.status_code == 404

    # POST /admin/test/start without token returns 401
    unauth_resp = await app_client.post(
        "/admin/test/start",
        json={"mode": "round_robin", "duration_s": 10.0, "lambda_per_client": 5.0, "heavy_ratio": 0.2, "seed": 42},
    )
    assert unauth_resp.status_code == 401

    # POST /admin/test/start with valid Bearer token succeeds and arms the test
    headers = _admin_headers()
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

    with open(TEST_LOG_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == TEST_LOG_COLUMNS
        assert reader.fieldnames is not None and len(reader.fieldnames) == 22
        assert len(TEST_SUMMARY_COLUMNS) == 19
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
    headers = _admin_headers()

    # Reset
    reset_resp = await app_client.post("/admin/stats/reset", headers=headers)
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "reset"

    # Summary
    summary_resp = await app_client.get("/admin/stats/summary", headers=headers)
    assert summary_resp.status_code == 200
    assert isinstance(summary_resp.json(), list)

    # Download (supports summary/log and test_summary/test_log)
    download_resp = await app_client.get("/admin/stats/download?file=test_summary", headers=headers)
    assert download_resp.status_code == 200
    assert "text/csv" in download_resp.headers.get("content-type", "")
    download_log_resp = await app_client.get("/admin/stats/download?file=test_log", headers=headers)
    assert download_log_resp.status_code == 200
    assert "test_id,mode,seed" in download_log_resp.text


@pytest.mark.asyncio
async def test_step_d_lifecycle_draining_timeouts_and_load_client(tmp_path: Path) -> None:
    """Step (d): verify StartTestRequest defaults/max, armed->running->draining->idle,
    draining 409 rejection, leftover timeout logging, archiving reset, and load_client CLI.
    """
    import asyncio

    from pydantic import ValidationError
    from scripts.load_client import build_deterministic_schedule, parse_args

    from app.api.admin import StartTestRequest, test_manager
    from app.core.config import Settings
    from app.core.logger import CSVTaskLogger
    from app.models.schemas import Telemetry

    end_test()

    # 1. StartTestRequest defaults & max=120 enforcement
    req_default = StartTestRequest(mode="milp")
    assert req_default.duration_s == 60.0
    assert req_default.lambda_per_client == 3.0
    assert req_default.heavy_ratio == 0.3
    assert req_default.seed == 42
    assert req_default.load_source == "external"

    with pytest.raises(ValidationError):
        StartTestRequest(mode="milp", duration_s=121.0)

    # 2. Archiving on reset_logs
    test_log = tmp_path / "test_log.csv"
    test_sum = tmp_path / "test_summary.csv"
    tmp_logger = CSVTaskLogger(log_path=test_log)
    tmp_logger.log_task({col: "val" for col in TEST_LOG_COLUMNS})
    tmp_logger.reset_logs(log_path=test_log, summary_path=test_sum)
    archived = list((tmp_path / "archive").glob("test_log_*.csv"))
    assert len(archived) == 1
    tmp_logger.close()

    # 3. Full armed -> running -> draining -> idle with slow leftover task timeout
    slow_gate = asyncio.Event()

    class SlowWorkerTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            body = request.content.decode("utf-8", errors="ignore")
            if "slow-client" in body:
                await asyncio.wait_for(slow_gate.wait(), timeout=2.0)
            return httpx.Response(
                200,
                json={
                    "task_id": "t",
                    "worker_id": "worker-1",
                    "status": "COMPLETED",
                    "queue_ms": 1.0,
                    "execution_ms": 4.0,
                    "result": {"cgpa": 9.0},
                },
            )

    worker_http = httpx.AsyncClient(transport=SlowWorkerTransport())
    app = create_app(
        settings=Settings(local_mode=True, seed_demo_workers=False),
        worker_http_client=worker_http,
    )
    await app.state.cluster_state.update_telemetry(
        Telemetry(
            worker_id="worker-1",
            ip_address="127.0.0.1",
            port=8001,
            cpu_percent=10.0,
            memory_total_mb=4096.0,
            memory_used_mb=512.0,
            memory_percent=12.5,
            load_avg_1m=0.1,
            active_task_count=0,
        )
    )

    orig_arm = test_manager.arming_delay_sec
    orig_drain = test_manager.drain_timeout_sec
    test_manager.arming_delay_sec = 0.25
    test_manager.drain_timeout_sec = 0.60
    headers = _admin_headers()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://lifecycle-test") as client:
            start_r = await client.post(
                "/admin/test/start",
                headers=headers,
                json={"mode": "round_robin", "duration_s": 0.35, "load_source": "external"},
            )
            assert start_r.status_code == 200
            tid = start_r.json()["test_id"]

            # Armed phase: logged with test_id="none"
            armed_task = await client.post("/tasks", json={"client_id": "pre-start", "task_type": "light"})
            assert armed_task.status_code == 200

            # Wait until running
            for _ in range(30):
                if (await client.get("/test/status")).json()["state"] == "running":
                    break
                await asyncio.sleep(0.02)
            assert (await client.get("/test/status")).json()["state"] == "running"

            # Fast tasks from multiple clients + 1 slow leftover task
            fast1 = await client.post("/tasks", json={"client_id": "laptop-1", "task_type": "light"})
            fast2 = await client.post("/tasks", json={"client_id": "web", "task_type": "light"})
            assert fast1.status_code == 200 and fast2.status_code == 200
            slow_future = asyncio.create_task(
                client.post(
                    "/tasks",
                    json={
                        "client_id": "slow-client",
                        "task_type": "light",
                        "payload": {
                            "marker": "slow-client",
                            "courses": [{"name": "C1", "credits": 4.0, "grade": 9.0}],
                        },
                    },
                )
            )
            await asyncio.sleep(0.02)

            # Wait for draining transition
            for _ in range(40):
                if (await client.get("/test/status")).json()["state"] == "draining":
                    break
                await asyncio.sleep(0.02)
            assert (await client.get("/test/status")).json()["state"] == "draining"

            # Draining rejects new tasks with 409 Conflict
            drain_reject = await client.post("/tasks", json={"client_id": "laptop-2", "task_type": "light"})
            assert drain_reject.status_code == 409

            # Wait for draining timeout + idle + summary generation
            for _ in range(50):
                if (await client.get("/test/status")).json()["state"] == "idle":
                    break
                await asyncio.sleep(0.03)
            assert (await client.get("/test/status")).json()["state"] == "idle"

            slow_gate.set()
            await slow_future

            csv_logger.flush()
            with open(TEST_LOG_PATH, encoding="utf-8") as f:
                rows = [r for r in csv.DictReader(f) if r.get("test_id") == tid]
            statuses_by_client = {r["client_id"]: r["status"] for r in rows}
            assert "pre-start" not in statuses_by_client
            assert statuses_by_client.get("laptop-1") == "ok"
            assert statuses_by_client.get("web") == "ok"
            assert statuses_by_client.get("slow-client") == "timeout"
            assert len(rows) == 3  # no duplicate row after slow task released

            all_summaries = (await client.get("/admin/stats/summary", headers=headers)).json()
            sum_rows = [r for r in all_summaries if r["test_id"] == tid]
            assert len(sum_rows) == 1
            assert int(sum_rows[0]["requests"]) == 3
            assert int(sum_rows[0]["failed"]) == 1
    finally:
        slow_gate.set()
        test_manager.arming_delay_sec = orig_arm
        test_manager.drain_timeout_sec = orig_drain
        await test_manager.stop()
        end_test()
        await worker_http.aclose()

    # 4. load_client CLI & determinism check
    os.environ["CB_BASE_URL"] = "https://demo.trycloudflare.com"
    try:
        parsed_env = parse_args(["--laptop-no", "2"])
        assert parsed_env.controller == "https://demo.trycloudflare.com"
        assert parsed_env.laptop_no == 2
        assert parsed_env.client_id is None
    finally:
        os.environ.pop("CB_BASE_URL", None)

    parsed_cli = parse_args(
        ["--controller", "http://192.168.1.10:8000", "--client-id", "laptop-1", "--laptop-no", "1"]
    )
    assert parsed_cli.controller == "http://192.168.1.10:8000"
    assert parsed_cli.client_id == "laptop-1"
    assert parsed_cli.laptop_no == 1
    assert build_deterministic_schedule(10.0, 3.0, 0.3, 42, 1) == build_deterministic_schedule(
        10.0, 3.0, 0.3, 42, 1
    )


@pytest.mark.asyncio
async def test_phase3_client_fields_validation_migration_rate_limit_and_regressions(
    tmp_path: Path,
) -> None:
    """Tests (d)-(i) + explicit 22/19 header counts for browser /client load support."""
    from scripts.load_client import send_single_task

    from app.core.config import Settings
    from app.core.logger import CSVTaskLogger
    from app.core.security import ClientRateLimiter
    from app.models.schemas import Telemetry

    end_test()

    # Explicit CSV column counts & schema tails
    assert len(TEST_LOG_COLUMNS) == 22
    assert TEST_LOG_COLUMNS[-2:] == ["client_rate", "client_task_type"]
    assert len(TEST_SUMMARY_COLUMNS) == 19
    assert TEST_SUMMARY_COLUMNS[-1] == "clients_seen"

    # Fast mock worker transport so we can exercise full POST /tasks pipeline deterministically
    class FastWorkerTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "task_id": "t-ok",
                    "worker_id": "worker-1",
                    "status": "COMPLETED",
                    "queue_ms": 0.5,
                    "execution_ms": 2.0,
                    "result": {"cgpa": 8.9},
                },
            )

    worker_http = httpx.AsyncClient(transport=FastWorkerTransport())
    app = create_app(
        settings=Settings(local_mode=True, seed_demo_workers=False),
        worker_http_client=worker_http,
    )
    await app.state.cluster_state.update_telemetry(
        Telemetry(
            worker_id="worker-1",
            ip_address="127.0.0.1",
            port=8001,
            cpu_percent=10.0,
            memory_total_mb=4096.0,
            memory_used_mb=512.0,
            memory_percent=12.5,
            load_avg_1m=0.1,
            active_task_count=0,
        )
    )

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://phase3-test") as client:
            # (f) Validation & boundary checks (10.0 -> 200, 10.1 -> 422, plus invalid values -> 422)
            for bad_payload in (
                {"client_id": "c-bad", "task_type": "light", "client_rate": 0.1},
                {"client_id": "c-bad", "task_type": "light", "client_rate": 10.1},
                {"client_id": "c-bad", "task_type": "light", "client_rate": 50},
                {"client_id": "c-bad", "task_type": "light", "client_rate": True},
                {"client_id": "c-bad", "task_type": "light", "client_task_type": "medium"},
                {"client_id": "c-bad", "task_type": "light", "client_task_type": ""},
            ):
                bad_resp = await client.post("/tasks", json=bad_payload)
                assert bad_resp.status_code == 422, f"Expected 422 for {bad_payload}, got {bad_resp.status_code}"

            boundary_ok = await client.post(
                "/tasks",
                json={
                    "client_id": "c-boundary-10",
                    "task_type": "light",
                    "client_rate": 10.0,
                    "client_task_type": "light",
                },
            )
            assert boundary_ok.status_code == 200

            # (d) Present vs omitted client_rate / client_task_type in test_log.csv
            cid_with = f"client-with-{os.getpid()}"
            cid_without = f"client-without-{os.getpid()}"
            ok_with = await client.post(
                "/tasks",
                json={
                    "client_id": cid_with,
                    "task_type": "heavy",
                    "size": 150000,
                    "client_rate": 3,
                    "client_task_type": "heavy",
                },
            )
            ok_without = await client.post(
                "/tasks",
                json={"client_id": cid_without, "task_type": "light"},
            )
            assert ok_with.status_code == 200
            assert ok_without.status_code == 200

            csv_logger.flush()
            with open(TEST_LOG_PATH, encoding="utf-8") as f:
                log_reader = csv.DictReader(f)
                assert log_reader.fieldnames == TEST_LOG_COLUMNS
                assert len(log_reader.fieldnames) == 22
                rows = list(log_reader)

            with_row = next(r for r in reversed(rows) if r["client_id"] == cid_with)
            without_row = next(r for r in reversed(rows) if r["client_id"] == cid_without)
            assert with_row["client_rate"] == "3.0"
            assert with_row["client_task_type"] == "heavy"
            assert without_row["client_rate"] == ""
            assert without_row["client_task_type"] == ""

            # (h) Rate limiter allows 10 req/s (350 requests in window > 300/min from one client_id) without 429
            burst_client = f"burst-10rps-{os.getpid()}"
            for idx in range(350):
                r = await client.post(
                    "/tasks",
                    json={
                        "client_id": burst_client,
                        "task_type": "light",
                        "client_rate": 10.0,
                        "client_task_type": "light",
                        "sent_at": idx,
                    },
                )
                assert r.status_code == 200

            # (i) Regressions: public "/" shape, load_client.send_single_task, and GET /client SPA
            pub_resp = await client.post(
                "/tasks",
                json={
                    "client_id": "public-web-client",
                    "task_type": "light",
                    "payload": {
                        "courses": [{"name": "Distributed Systems", "credits": 4, "grade": 9.0}]
                    },
                },
            )
            assert pub_resp.status_code == 200

            counter = {"ok": 0, "failed": 0}
            await send_single_task(client, "http://phase3-test", "laptop-1", "heavy", counter)
            assert counter == {"ok": 1, "failed": 0}

            client_spa = await client.get("/client", follow_redirects=False)
            assert client_spa.status_code == 200
            assert "text/html" in client_spa.headers.get("content-type", "")
    finally:
        await worker_http.aclose()

    # Default ClientRateLimiter allows 10 req/s over 60s (= 600 hits) without 429
    limiter = ClientRateLimiter()
    for _ in range(600):
        limiter.check_and_record("client-10rps-window", test_active=True)
        limiter.check_and_record("client-10rps-idle", test_active=False)

    # (e) clients_seen == 3 scoped strictly by test_id (including web, excluding blank / other tests)
    sum_log = tmp_path / "clients_log.csv"
    sum_out = tmp_path / "clients_summary.csv"
    with open(sum_log, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TEST_LOG_COLUMNS)
        w.writeheader()
        base = {col: "" for col in TEST_LOG_COLUMNS}
        for seq, (tid, cid) in enumerate(
            [
                ("tid-target", "client-1"),
                ("tid-target", "client-2"),
                ("tid-target", "web"),
                ("tid-target", "client-1"),
                ("tid-target", ""),
                ("tid-other", "client-99"),
            ],
            start=1,
        ):
            w.writerow({
                **base,
                "test_id": tid,
                "mode": "milp",
                "seed": "42",
                "duration_s": "30",
                "lambda_per_client": "3",
                "heavy_ratio": "0.3",
                "client_id": cid,
                "task_id": f"t-{seq}",
                "task_type": "light",
                "scheduler_used": "ortools_milp",
                "dispatch_seq": str(seq),
                "assigned_worker": f"worker-{((seq - 1) % 3) + 1}",
                "queue_ms": "1.0",
                "exec_ms": "5.0",
                "total_ms": "6.0",
                "status": "ok",
                "failover": "false",
            })

    summary = write_test_summary(
        test_id="tid-target",
        mode="milp",
        seed=42,
        duration_s=30.0,
        lambda_per_client=3.0,
        heavy_ratio=0.3,
        log_path=sum_log,
        summary_path=sum_out,
    )
    assert summary["clients_seen"] == 3
    with open(sum_out, encoding="utf-8") as f:
        s_reader = csv.DictReader(f)
        assert s_reader.fieldnames == TEST_SUMMARY_COLUMNS
        assert len(s_reader.fieldnames) == 19
        s_rows = list(s_reader)
    assert len(s_rows) == 1
    assert s_rows[0]["clients_seen"] == "3"

    # (g) Migration of legacy 20-col test_log.csv (3 rows) & 18-col test_summary.csv (1 row)
    mig_log = tmp_path / "legacy_log.csv"
    mig_sum = tmp_path / "legacy_summary.csv"
    with open(mig_log, "w", newline="", encoding="utf-8") as f:
        lw = csv.writer(f)
        lw.writerow(TEST_LOG_COLUMNS[:20])
        for i in range(1, 4):
            lw.writerow([
                "legacy-tid", "milp", "42", "30", "3.0", "0.3",
                f"c-{i}", f"lt-{i}", "light", "1700000000", "milp", str(i),
                f"worker-{i}", "0", "10.00", "1.00", "10.00", "11.00", "ok", "false",
            ])
    with open(mig_sum, "w", newline="", encoding="utf-8") as f:
        sw = csv.writer(f)
        sw.writerow(TEST_SUMMARY_COLUMNS[:18])
        sw.writerow([
            "legacy-sum-0", "round_robin", "42", "30", "3.0", "0.3",
            "10", "0", "12.0", "11.0", "18.0", "22.0", "1.0",
            "0.33", "40.0", "40.0", "40.0", "0.0",
        ])

    mig_logger = CSVTaskLogger(log_path=mig_log)
    mig_logger.flush()
    write_test_summary(
        test_id="legacy-tid",
        mode="milp",
        seed=42,
        duration_s=30.0,
        lambda_per_client=3.0,
        heavy_ratio=0.3,
        log_path=mig_log,
        summary_path=mig_sum,
    )
    mig_logger.close()

    with open(mig_log, encoding="utf-8") as f:
        ml_reader = csv.DictReader(f)
        assert len(ml_reader.fieldnames or []) == 22
        ml_rows = list(ml_reader)
    assert len(ml_rows) == 3
    assert all(r["client_rate"] == "" and r["client_task_type"] == "" for r in ml_rows)

    with open(mig_sum, encoding="utf-8") as f:
        ms_reader = csv.DictReader(f)
        assert len(ms_reader.fieldnames or []) == 19
        ms_rows = list(ms_reader)
    assert len(ms_rows) == 2
    assert ms_rows[0]["test_id"] == "legacy-sum-0" and ms_rows[0]["clients_seen"] == ""
    assert ms_rows[1]["test_id"] == "legacy-tid" and ms_rows[1]["clients_seen"] == "3"


@pytest.mark.asyncio
async def test_start_test_defaults_external_and_explicit_simulator_spawns_sim_clients() -> None:
    """POST /admin/test/start defaults to load_source='external'; explicit 'simulator' spawns sim-1..3."""
    import asyncio

    from app.api.admin import ActiveTestManager, StartTestRequest, test_manager
    from app.core.config import Settings
    from app.core.simulator import simulator_manager
    from app.models.schemas import Telemetry

    assert StartTestRequest(mode="milp").load_source == "external"
    assert ActiveTestManager().load_source == "external"

    class FastWorkerTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "task_id": "t",
                    "worker_id": "worker-1",
                    "status": "COMPLETED",
                    "queue_ms": 0.5,
                    "execution_ms": 2.0,
                    "result": {"cgpa": 9.0},
                },
            )

    worker_http = httpx.AsyncClient(transport=FastWorkerTransport())
    app = create_app(
        settings=Settings(local_mode=True, seed_demo_workers=False),
        worker_http_client=worker_http,
    )
    for idx in (1, 2, 3):
        await app.state.cluster_state.update_telemetry(
            Telemetry(
                worker_id=f"worker-{idx}",
                ip_address="127.0.0.1",
                port=8000 + idx,
                cpu_percent=10.0,
                memory_total_mb=4096.0,
                memory_used_mb=512.0,
                memory_percent=12.5,
                load_avg_1m=0.1,
                active_task_count=0,
            )
        )

    orig_arm = test_manager.arming_delay_sec
    orig_drain = test_manager.drain_timeout_sec
    test_manager.arming_delay_sec = 0.05
    test_manager.drain_timeout_sec = 0.40
    headers = _admin_headers()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://default-load-source") as client:
            # 1. Default start (omitting load_source) must stay 'external' and NOT spawn simulator clients
            end_test()
            await simulator_manager.stop()
            ext_start = await client.post(
                "/admin/test/start",
                headers=headers,
                json={"mode": "round_robin", "duration_s": 0.25, "lambda_per_client": 8.0},
            )
            assert ext_start.status_code == 200
            ext_data = ext_start.json()
            assert ext_data["load_source"] == "external"
            ext_tid = ext_data["test_id"]

            for _ in range(40):
                if (await client.get("/test/status")).json()["state"] == "idle":
                    break
                await asyncio.sleep(0.03)
            assert (await client.get("/test/status")).json()["state"] == "idle"
            assert simulator_manager.get_counters()["sent"] == 0

            csv_logger.flush()
            with open(TEST_LOG_PATH, encoding="utf-8") as f:
                ext_clients = {r["client_id"] for r in csv.DictReader(f) if r.get("test_id") == ext_tid}
            assert not any(c.startswith("sim-") for c in ext_clients)

            # 2. Explicit load_source='simulator' must still spawn sim-1, sim-2, sim-3
            sim_start = await client.post(
                "/admin/test/start",
                headers=headers,
                json={
                    "mode": "round_robin",
                    "duration_s": 0.50,
                    "lambda_per_client": 8.0,
                    "heavy_ratio": 0.0,
                    "load_source": "simulator",
                },
            )
            assert sim_start.status_code == 200
            sim_data = sim_start.json()
            assert sim_data["load_source"] == "simulator"
            sim_tid = sim_data["test_id"]

            for _ in range(60):
                if (await client.get("/test/status")).json()["state"] == "idle":
                    break
                await asyncio.sleep(0.03)
            assert (await client.get("/test/status")).json()["state"] == "idle"
            assert simulator_manager.get_counters()["sent"] >= 3

            csv_logger.flush()
            with open(TEST_LOG_PATH, encoding="utf-8") as f:
                sim_clients = {r["client_id"] for r in csv.DictReader(f) if r.get("test_id") == sim_tid}
            assert {"sim-1", "sim-2", "sim-3"}.issubset(sim_clients)
    finally:
        await simulator_manager.stop()
        test_manager.arming_delay_sec = orig_arm
        test_manager.drain_timeout_sec = orig_drain
        await test_manager.stop()
        end_test()
        await worker_http.aclose()
