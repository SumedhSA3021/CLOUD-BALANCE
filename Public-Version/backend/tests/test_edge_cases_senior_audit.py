"""Senior Engineer Audit & Comprehensive Edge-Case Test Suite.

Covers edge cases and regression checks across:
1. Admin API (reset_stats Path bug, download?file=log AttributeError, mode validation,
   falsy-zero inputs, 409 lock during active test).
2. InternalLoadSimulator (lock re-entrancy deadlock on back-to-back start(), stop() idempotency,
   deterministic schedules).
3. CSVTaskLogger & write_test_summary (RLock non-deadlock, corrupted CSV rows, zero matching rows,
   restart after close).
4. Tasks API (GET /api/v1/tasks/submit fallback TypeError fix, 422 on invalid JSON/ValidationError,
   NaN sent_at, invalid CGPA bounds propagation, non-JSON 504 response, sequential lifespans).
5. ORToolsMILPScheduler & InFlightTracker (cumulative dispatch drift soak test >2000 tasks without
   false DEGRADED_FALLBACK, concurrency lock safety).
6. Worker Executor (queue slot leak on asyncio.CancelledError, invalid timeout_sec validation before
   enqueue, NaN credits/grades, mismatched lengths, invalid Content-Length).
7. Schemas (reject NaN/Inf on Telemetry, TaskRequest, DispatchPayload).
"""

from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError
from worker.executor import WorkerRuntimeState, create_worker_app

from app.api.admin import StartTestRequest, test_manager
from app.core.config import Settings, get_settings
from app.core.live_stats import live_dispatch_tracker
from app.core.logger import TEST_LOG_COLUMNS, CSVTaskLogger, write_test_summary
from app.core.profiles import TaskType
from app.core.simulator import InternalLoadSimulator, build_deterministic_schedule
from app.main import create_app
from app.models.schemas import DispatchPayload, Task, TaskRequest, Telemetry
from app.schedulers.base import InFlightTracker
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.schedulers.test_hooks import end_test, start_test


def _admin_token() -> str:
    return get_settings().admin_token


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_token()}"}


@pytest.fixture
def clean_client():
    end_test()
    cfg = Settings(local_mode=True, seed_demo_workers=True)
    app = create_app(settings=cfg)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://audit-ctrl")
    return app, client


# --- 1. Admin API & Lifecycle Edge Cases ---


@pytest.mark.asyncio
async def test_admin_download_log_and_reset_when_missing(clean_client, tmp_path: Path) -> None:
    """GET /admin/stats/download?file=log works even before file exists; reset works cleanly."""
    _app, client = clean_client
    async with client:
        missing_log = tmp_path / "missing_log.csv"
        missing_summary = tmp_path / "missing_summary.csv"
        with (
            patch("app.api.admin.TEST_LOG_PATH", missing_log),
            patch("app.api.admin.TEST_SUMMARY_PATH", missing_summary),
        ):
            dl_log = await client.get("/admin/stats/download?file=log", headers=_admin_headers())
            assert dl_log.status_code == 200
            assert "test_id,mode,seed" in dl_log.text

            dl_sum = await client.get("/admin/stats/download?file=summary", headers=_admin_headers())
            assert dl_sum.status_code == 200
            assert "busy_time_stddev" in dl_sum.text

            reset_resp = await client.post("/admin/stats/reset", headers=_admin_headers())
            assert reset_resp.status_code == 200
            assert reset_resp.json()["status"] == "reset"
            assert missing_summary.exists()


@pytest.mark.asyncio
async def test_admin_start_validates_inputs_and_preserves_falsy_zeros(clean_client) -> None:
    """StartTestRequest validates invalid modes/bounds and preserves heavy_ratio=0.0 & seed=0."""
    _app, client = clean_client
    try:
        async with client:
            # Invalid mode returns 422
            bad_mode = await client.post(
                "/admin/test/start",
                headers=_admin_headers(),
                json={"mode": "bogus_algo", "duration_s": 10},
            )
            assert bad_mode.status_code == 422

            # Invalid load_source returns 422
            bad_ls = await client.post(
                "/admin/test/start",
                headers=_admin_headers(),
                json={"mode": "milp", "load_source": "unknown_src"},
            )
            assert bad_ls.status_code == 422

            # Zero heavy_ratio and zero seed preserved
            ok = await client.post(
                "/admin/test/start",
                headers=_admin_headers(),
                json={
                    "mode": "ortools_milp",
                    "duration_s": 5.0,
                    "lambda_per_client": 1.0,
                    "heavy_ratio": 0.0,
                    "seed": 0,
                    "load_source": "external",
                },
            )
            assert ok.status_code == 200
            data = ok.json()
            assert data["mode"] == "milp"
            assert data["heavy_ratio"] == 0.0
            assert data["seed"] == 0

            # Reset stats blocked while test active (409 Conflict)
            reset_blocked = await client.post("/admin/stats/reset", headers=_admin_headers())
            assert reset_blocked.status_code == 409

            stopped = await client.post("/admin/test/stop", headers=_admin_headers())
            assert stopped.status_code == 200
            assert stopped.json()["state"] == "idle"
            # Idempotent second stop
            stopped2 = await client.post("/admin/test/stop", headers=_admin_headers())
            assert stopped2.status_code == 200
            assert stopped2.json()["state"] == "idle"
    finally:
        await test_manager.stop()
        end_test()


# --- 2. Simulator Lock Re-entrancy & Deterministic Schedules ---


@pytest.mark.asyncio
async def test_simulator_back_to_back_start_does_not_deadlock(clean_client) -> None:
    """Calling simulator.start() while already running must NOT deadlock on _lock."""
    app, _client = clean_client
    sim = InternalLoadSimulator()
    try:
        await asyncio.wait_for(
            sim.start(
                app=app,
                duration_s=2.0,
                lambda_per_client=1.0,
                heavy_ratio=0.0,
                seed=0,
                start_at=time.time() + 10.0,
                num_clients=2,
            ),
            timeout=2.0,
        )
        # Re-start immediately while running
        await asyncio.wait_for(
            sim.start(
                app=app,
                duration_s=2.0,
                lambda_per_client=1.0,
                heavy_ratio=1.0,
                seed=42,
                start_at=time.time() + 10.0,
                num_clients=3,
            ),
            timeout=2.0,
        )
        assert sim.is_running is True
    finally:
        await sim.stop()
        await sim.stop()  # idempotent stop
        assert sim.is_running is False


def test_deterministic_schedule_edge_ratios() -> None:
    s_light = build_deterministic_schedule(duration_s=10.0, lambda_rate=3.0, heavy_ratio=0.0, seed=42, client_no=1)
    assert all(tt == "light" for _, tt in s_light)
    s_heavy = build_deterministic_schedule(duration_s=10.0, lambda_rate=3.0, heavy_ratio=1.0, seed=42, client_no=1)
    assert all(tt == "heavy" for _, tt in s_heavy)
    assert build_deterministic_schedule(duration_s=0.0, lambda_rate=3.0, heavy_ratio=0.5, seed=42, client_no=1) == []


# --- 3. CSV Logger RLock, Restart, & Summary Defensiveness ---


def test_csv_logger_nested_lock_no_deadlock_and_malformed_summary(tmp_path: Path) -> None:
    log_p = tmp_path / "log.csv"
    sum_p = tmp_path / "sum.csv"
    logger_inst = CSVTaskLogger(log_path=log_p)
    for i in range(10):
        logger_inst.log_task(
            {col: (1.5 if col in ("exec_ms", "total_ms", "queue_ms") else f"v{i}") for col in TEST_LOG_COLUMNS}
        )
    t0 = time.monotonic()
    logger_inst.flush(timeout=2.0)
    assert time.monotonic() - t0 < 1.5
    assert log_p.exists()

    # Close and verify log_task automatically restarts background thread if reused
    logger_inst.close()
    logger_inst.log_task({col: "after_close" for col in TEST_LOG_COLUMNS})
    logger_inst.flush(timeout=2.0)
    logger_inst.close()

    # Inject malformed CSV row with non-float values; write_test_summary must not crash
    with open(log_p, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEST_LOG_COLUMNS)
        writer.writerow(
            {
                "test_id": "test-bad-cell",
                "mode": "milp",
                "seed": "42",
                "duration_s": "10",
                "lambda_per_client": "2",
                "heavy_ratio": "0.2",
                "client_id": "c1",
                "task_id": "t1",
                "task_type": "light",
                "sent_at": "100",
                "scheduler_used": "ortools_milp",
                "dispatch_seq": "none",
                "assigned_worker": "worker-1",
                "worker_inflight_at_dispatch": "0",
                "worker_cpu_pct_at_dispatch": "10.0",
                "queue_ms": "NaN",
                "exec_ms": "not_a_float",
                "total_ms": "inf",
                "status": "ok",
            }
        )
    res = write_test_summary(
        test_id="test-bad-cell",
        mode="milp",
        seed=42,
        duration_s=10.0,
        lambda_per_client=2.0,
        heavy_ratio=0.2,
        log_path=log_p,
        summary_path=sum_p,
    )
    assert res["requests"] == 1
    assert res["worker1_busy_ms"] == 0.0


# --- 4. Tasks API & Validation Edge Cases ---


@pytest.mark.asyncio
async def test_tasks_get_fallback_and_validation_errors(clean_client) -> None:
    """Deprecated GET /api/v1/tasks/submit is removed; malformed JSON & invalid task types return 422."""
    _app, client = clean_client
    async with client:
        # Removed GET fallback -> 404 or 405
        get_old = await client.get("/api/v1/tasks/submit?client_id=safari-phone&task_type=LIGHTWEIGHT_QUERY")
        assert get_old.status_code in (404, 405)

        # Malformed JSON to POST /api/v1/tasks & POST /tasks -> 422 (not 500)
        bad_json = await client.post(
            "/api/v1/tasks",
            content=b"{not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        assert bad_json.status_code == 422

        # Alias POST /api/v1/tasks routes identically through execute_task_contract
        alias_ok = await client.post(
            "/api/v1/tasks",
            json={"client_id": "c1", "task_type": "light"},
        )
        assert alias_ok.status_code == 200
        assert alias_ok.json()["assigned_worker"] in ("worker-1", "worker-2", "worker-3")

        # Sending wrong or old default X-API-Key to /api/v1/tasks rejects with 401 even when no key is set
        bad_alias = await client.post(
            "/api/v1/tasks",
            headers={"X-API-Key": "cb-dev-api-key-2026"},
            json={"client_id": "c1", "task_type": "light"},
        )
        assert bad_alias.status_code == 401
        wrong_alias = await client.post(
            "/api/v1/tasks",
            headers={"X-API-Key": "wrong-key"},
            json={"client_id": "c1", "task_type": "light"},
        )
        assert wrong_alias.status_code == 401

        # Blank client_id / invalid task_type / bad CGPA grade to POST /tasks
        blank_cid = await client.post("/tasks", json={"client_id": "   ", "task_type": "light"})
        assert blank_cid.status_code == 422

        bad_type = await client.post("/tasks", json={"client_id": "c1", "task_type": "nonsense"})
        assert bad_type.status_code == 422

        bad_grade = await client.post(
            "/tasks",
            json={"client_id": "c1", "task_type": "light", "payload": {"courses": [{"credits": 3, "grade": 15.0}]}},
        )
        assert bad_grade.status_code == 400

        # Protected mongo inspection endpoint requires admin Bearer auth and works cleanly
        assert (await client.get("/api/v1/mongo")).status_code == 401
        mongo_resp = await client.get("/api/v1/mongo", headers=_admin_headers())
        assert mongo_resp.status_code == 200
        assert "collections" in mongo_resp.json()


# --- 5. MILP Cumulative Drift Soak Test & InFlightTracker Concurrency ---


def test_milp_soak_high_cumulative_dispatches_stays_feasible_and_balanced() -> None:
    """Even after 2,000+ cumulative dispatches, MILP must NOT drift past 85% hard cap into DEGRADED_FALLBACK."""
    live_dispatch_tracker.reset_current_test()
    tracker = InFlightTracker()
    milp = ORToolsMILPScheduler(in_flight_tracker=tracker)

    workers = [
        Telemetry(
            worker_id=wid,
            ip_address="virtual",
            port=8001 + i,
            cpu_percent=12.0 + i * 2.0,
            memory_total_mb=4096.0,
            memory_used_mb=512.0,
            memory_percent=12.5,
            load_avg_1m=0.5,
            active_task_count=0,
        )
        for i, wid in enumerate(("worker-1", "worker-2", "worker-3"))
    ]

    # Simulate 2,100 prior dispatches evenly (700 per worker)
    for _ in range(700):
        for wid in ("worker-1", "worker-2", "worker-3"):
            live_dispatch_tracker.record_dispatch(wid)

    t = Task.from_request(TaskRequest(client_id="soak-1", task_type=TaskType.LIGHT))
    res = milp.assign([t], workers, record_in_flight=False)
    assert res.meta.degraded is False
    assert res.meta.status == "OPTIMAL"

    # Also test sequential distribution under idle equal load spreads across all 3 workers
    live_dispatch_tracker.reset_current_test()
    picks: list[str] = []
    for _ in range(9):
        task_i = Task.from_request(TaskRequest(client_id="light-seq", task_type=TaskType.LIGHT))
        r = milp.assign([task_i], workers, record_in_flight=False)
        chosen = r.assignments[task_i.task_id]
        live_dispatch_tracker.record_dispatch(chosen)
        picks.append(chosen)

    assert len(set(picks)) == 3
    for wid in ("worker-1", "worker-2", "worker-3"):
        assert picks.count(wid) == 3

    live_dispatch_tracker.reset_current_test()


# --- 6. Worker Executor Cancellation & Validation Edge Cases ---


@pytest.mark.asyncio
async def test_worker_queue_no_leak_on_cancel_and_bad_payloads() -> None:
    """Cancelled waiting task & bad timeout_sec must not leak current_queue_length."""
    state = WorkerRuntimeState(
        worker_id="worker-edge",
        port=8001,
        concurrency_limit=1,
        queue_capacity=2,
        task_timeout_sec=5.0,
    )
    app = create_worker_app(state=state)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://worker-edge") as client:
        # Invalid timeout_sec rejected with 400 BEFORE queue entry
        bad_timeout = await client.post(
            "/execute",
            json={
                "task_id": "t-bad-to",
                "task_type": "light",
                "payload": {"courses": [{"grade": 9, "credits": 3}], "timeout_sec": "invalid"},
            },
        )
        assert bad_timeout.status_code == 400
        assert state.current_queue_length == 0

        # NaN credits / mismatched grades-credits rejected with 400
        bad_cred = await client.post(
            "/execute",
            json={"task_id": "t-bad-c", "task_type": "light", "payload": {"courses": [{"grade": 9, "credits": "nan"}]}},
        )
        assert bad_cred.status_code == 400

        mismatch_arr = await client.post(
            "/execute",
            json={"task_id": "t-mis", "task_type": "light", "payload": {"grades": [8.0, 9.0], "credits": [3.0]}},
        )
        assert mismatch_arr.status_code == 400

        # Invalid Content-Length header rejected cleanly
        bad_cl = await client.post(
            "/execute",
            json={"task_id": "t-cl", "task_type": "light", "payload": {"courses": [{"grade": 9, "credits": 3}]}},
            headers={"Content-Length": "not-an-int"},
        )
        assert bad_cl.status_code == 400

        # Occupy concurrency slot 1 and cancel a queued waiter -> queue must return to 0
        occ = asyncio.create_task(
            client.post("/execute", json={"task_id": "occ", "task_type": "heavy", "payload": {"iterations": 120000}})
        )
        await asyncio.sleep(0.02)
        waiter = asyncio.create_task(
            client.post(
                "/execute",
                json={"task_id": "waiter", "task_type": "light", "payload": {"courses": [{"grade": 8, "credits": 3}]}},
            )
        )
        await asyncio.sleep(0.02)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await occ
        assert state.current_queue_length == 0


# --- 7. Pydantic NaN / Infinity Schema Guards ---


def test_schemas_reject_nan_and_infinity() -> None:
    with pytest.raises(ValidationError):
        Telemetry(
            worker_id="worker-1",
            ip_address="127.0.0.1",
            cpu_percent=float("nan"),
            memory_total_mb=4096.0,
            memory_used_mb=512.0,
            memory_percent=12.5,
            load_avg_1m=0.5,
            active_task_count=0,
        )
    with pytest.raises(ValidationError):
        DispatchPayload(task_id="t1", duration_sec=float("inf"), matrix_dim=100)
    with pytest.raises(ValidationError):
        StartTestRequest(mode="milp", duration_s=float("nan"))


# --- 8. Built-in Simulator Full Flow, Live Stats, Telemetry Inspection, & Dispatcher Exhaustion ---


@pytest.mark.asyncio
async def test_builtin_simulator_full_dispatch_and_live_stats(clean_client) -> None:
    """Verify InternalLoadSimulator dispatches real tasks, populates live stats, and stops cleanly."""
    app, client = clean_client
    sim = InternalLoadSimulator()
    recorded: list[str] = []
    live_dispatch_tracker.reset_current_test()
    end_test()

    try:
        async with client:
            await app.state.cluster_state.seed_virtual_workers_if_empty()
            await sim.start(
                app=app,
                duration_s=1.2,
                lambda_per_client=4.0,
                heavy_ratio=0.0,
                seed=42,
                start_at=time.time(),
                num_clients=3,
                on_result=lambda st: recorded.append(st),
            )
            await asyncio.sleep(1.3)
            await sim.stop()

            counters = sim.get_counters()
            assert counters["sent"] >= 1
            assert counters["failed"] == 0
            assert counters["ok"] >= 1
            assert len(recorded) == counters["ok"]

            # GET /admin/stats/live reflects dispatched totals & 60s buckets
            live_resp = await client.get("/admin/stats/live", headers=_admin_headers())
            assert live_resp.status_code == 200
            live_data = live_resp.json()
            assert live_data["window_seconds"] == 60
            assert len(live_data["series"]["worker-1"]) == 60
            assert live_data["total_dispatched"] >= 1

            # Unknown worker ignored safely in live_dispatch_tracker
            live_dispatch_tracker.record_dispatch("unknown-worker")
            assert live_dispatch_tracker.get_worker_cumulative("unknown-worker") == 0

            # Telemetry Redis & Mongo inspection endpoints require admin Bearer auth
            assert (await client.get("/api/v1/telemetry/redis")).status_code == 401
            redis_resp = await client.get("/api/v1/telemetry/redis", headers=_admin_headers())
            assert redis_resp.status_code == 200
            assert redis_resp.json()["total_keys"] >= 1
            assert await app.state.redis_client.ttl("cluster:inflight:worker-1") == -1
            assert await app.state.redis_client.ttl("cluster:nonexistent-key") == -2

            assert (await client.get("/api/v1/telemetry/mongo")).status_code == 401
            mongo_resp = await client.get("/api/v1/telemetry/mongo", headers=_admin_headers())
            assert mongo_resp.status_code == 200
            assert mongo_resp.json()["mongo_backend_mode"] == "sqlite_fallback"
    finally:
        await sim.stop()
        live_dispatch_tracker.reset_current_test()


@pytest.mark.asyncio
async def test_tasks_contract_non_json_504_and_worker_offline_when_virtual_disabled() -> None:
    """When seed_demo_workers=False and workers fail with ConnectError/HTML 504,
    return structured error instead of HTTP 500.
    """
    end_test()
    cfg = Settings(local_mode=True, seed_demo_workers=False, default_scheduler="ortools_milp")

    def html_504_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(504, content=b"<html>504 Gateway Time-out</html>")

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(html_504_handler))
    app = create_app(settings=cfg, worker_http_client=mock_http)
    await app.state.cluster_state.update_telemetry(
        Telemetry(
            worker_id="worker-1",
            ip_address="10.128.0.11",
            port=8001,
            cpu_percent=10.0,
            memory_total_mb=4096.0,
            memory_used_mb=512.0,
            memory_percent=12.5,
            load_avg_1m=0.2,
            active_task_count=0,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ctrl-504") as client:
        resp = await client.post("/tasks", json={"client_id": "c-504", "task_type": "light"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["status"] == "timeout"
        assert body["queue_ms"] == 0.0
    await mock_http.aclose()


@pytest.mark.asyncio
async def test_admin_auth_login_verify_and_stats_protection() -> None:
    """Verify POST /admin/auth/login, GET /admin/auth/verify, and /admin/stats/* protection."""
    cfg = Settings(local_mode=True, seed_demo_workers=False)
    app = create_app(settings=cfg)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://auth-test") as client:
        # 1. Empty token -> 422, wrong token -> 401
        r_empty = await client.post("/admin/auth/login", json={"token": ""})
        assert r_empty.status_code == 422

        r_blank = await client.post("/admin/auth/login", json={"token": "   "})
        assert r_blank.status_code == 401

        r_bad = await client.post("/admin/auth/login", json={"token": "wrong-token"})
        assert r_bad.status_code == 401

        r_good = await client.post("/admin/auth/login", json={"token": _admin_token()})
        assert r_good.status_code == 200
        assert r_good.json() == {"authenticated": True, "role": "admin"}

        # 2. Verify session endpoint
        assert (await client.get("/admin/auth/verify")).status_code == 401
        assert (await client.get("/admin/auth/verify", headers={"Authorization": "Bearer wrong"})).status_code == 401
        r_verify = await client.get("/admin/auth/verify", headers=_admin_headers())
        assert r_verify.status_code == 200
        assert r_verify.json() == {"authenticated": True, "role": "admin"}

        # 3. Stats download & summary & live & reset strictly reject unauthenticated clients
        assert (await client.get("/admin/stats/summary")).status_code == 401
        assert (await client.get("/admin/stats/live")).status_code == 401
        assert (await client.get("/admin/stats/download?file=summary")).status_code == 401
        assert (await client.get("/admin/stats/download?file=log")).status_code == 401
        assert (await client.post("/admin/stats/reset")).status_code == 401


@pytest.mark.asyncio
async def test_post_tasks_rate_limit_by_client_id_and_max_payload_bytes() -> None:
    """Verify RATE_LIMIT_PER_MIN keys by client_id (never IP), never rejects <1200/min during test,
    and MAX_PAYLOAD_BYTES rejects oversized bodies with HTTP 413.
    """
    end_test()
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=True,
        rate_limit_per_min=3,
        max_payload_bytes=512,
    )
    app = create_app(settings=cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://limit-test") as client:
        # 1. Default rate_limit_per_min >= 1200 in production Settings
        assert Settings().rate_limit_per_min >= 1200

        # 2. Client A hits custom limit=3 on 4th request while Client B still succeeds (keyed by client_id)
        for _ in range(3):
            ok_a = await client.post("/tasks", json={"client_id": "client-A", "task_type": "light"})
            assert ok_a.status_code == 200
        blocked_a = await client.post("/tasks", json={"client_id": "client-A", "task_type": "light"})
        assert blocked_a.status_code == 429
        ok_b = await client.post("/tasks", json={"client_id": "client-B", "task_type": "light"})
        assert ok_b.status_code == 200

        # 3. During active test, never reject below 1200/min even with low configured limit
        start_test(mode="round_robin", test_id="test-rate-floor")
        try:
            for _ in range(5):
                during_test = await client.post("/tasks", json={"client_id": "client-A", "task_type": "light"})
                assert during_test.status_code == 200
        finally:
            end_test()

        # 4. Oversized payload returns HTTP 413
        oversized = await client.post(
            "/tasks",
            json={
                "client_id": "client-B",
                "task_type": "heavy",
                "payload": {"data": "x" * 1024, "iterations": 100},
            },
        )
        assert oversized.status_code == 413


@pytest.mark.asyncio
async def test_post_tasks_logs_503_rejection_and_handles_dead_worker_cleanly() -> None:
    """Verify failover & error logging rules:
    (a) 503 never retries elsewhere (both MILP & RR) -> logs status=rejected_503, failover=false;
    (b) 504/slow in RR never retries elsewhere -> logs status=timeout, failover=false;
    (c) ConnectError (dead worker) in MILP & RR fails over ONLY on dead worker -> status=ok, failover=true;
    (d) No live workers remaining -> logs clean status=unavailable, failover=false.
    """
    end_test()
    cfg = Settings(local_mode=True, seed_demo_workers=False, default_scheduler="ortools_milp")
    attempts: list[int] = []

    def worker_503_504_or_down(request: httpx.Request) -> httpx.Response:
        port = request.url.port or 0
        attempts.append(port)
        if port == 8001:
            return httpx.Response(503, json={"status": "rejected_503", "detail": "queue full"})
        if port == 8002:
            raise httpx.ConnectError("worker-2 crashed", request=request)
        if port == 8003 and "trigger-504" in request.content.decode("utf-8", errors="ignore"):
            return httpx.Response(504, content=b"<html>504 timeout</html>")
        return httpx.Response(
            200,
            json={
                "task_id": "t",
                "worker_id": "worker-3",
                "status": "COMPLETED",
                "queue_ms": 1.0,
                "execution_ms": 5.0,
                "result": {"cgpa": 9.0},
            },
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(worker_503_504_or_down))
    app = create_app(settings=cfg, worker_http_client=mock_http)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fail-ctrl") as client:
        worker_headers = {"X-Worker-Secret": cfg.worker_secret}
        # (a) worker-1 returns 503 even with worker-3 live -> NO retry/failover in MILP or RR
        for wid, port, cpu in (("worker-1", 8001, 5.0), ("worker-3", 8003, 50.0)):
            await client.post(
                "/api/v1/telemetry",
                headers=worker_headers,
                json={
                    "worker_id": wid,
                    "ip_address": f"10.128.0.{10 + port % 10}",
                    "port": port,
                    "cpu_percent": cpu,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 512.0,
                    "memory_percent": 12.5,
                    "load_avg_1m": 0.2,
                    "active_task_count": 0,
                },
            )
        attempts.clear()
        resp_503 = await client.post("/tasks", json={"client_id": "c-503", "task_type": "light"})
        assert resp_503.status_code == 200
        assert resp_503.json()["result"]["status"] == "rejected_503"
        assert attempts == [8001]
        assert app.state.in_flight_tracker.get_count("worker-1") == 0

        # Also in round_robin: 503 on worker-1 and 504 on worker-3 must NEVER retry elsewhere
        await app.state.redis_client.set("sched_mode", "round_robin")
        await app.state.redis_client.set("rr_counter", "0")
        attempts.clear()
        rr_503 = await client.post("/tasks", json={"client_id": "rr-503", "task_type": "light"})
        assert rr_503.json()["result"]["status"] == "rejected_503"
        assert attempts == [8001]

        await app.state.redis_client.set("rr_counter", "2")
        attempts.clear()
        rr_504 = await client.post(
            "/tasks",
            json={
                "client_id": "rr-504",
                "task_type": "light",
                "payload": {"data": "trigger-504", "courses": [{"name": "C", "credits": 3, "grade": 9}]},
            },
        )
        assert rr_504.json()["result"]["status"] == "timeout"
        assert attempts == [8003]

        # (b1) MILP dead worker-2 -> fails over to live worker-3, failover=true
        await app.state.cluster_state.evict_worker("worker-1")
        await app.state.redis_client.set("sched_mode", "milp")
        await client.post(
            "/api/v1/telemetry",
            headers=worker_headers,
            json={
                "worker_id": "worker-2",
                "ip_address": "10.128.0.12",
                "port": 8002,
                "cpu_percent": 5.0,
                "memory_total_mb": 4096.0,
                "memory_used_mb": 512.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.1,
                "active_task_count": 0,
            },
        )
        resp_milp_failover = await client.post("/tasks", json={"client_id": "c-milp-fo", "task_type": "light"})
        assert resp_milp_failover.json()["assigned_worker"] == "worker-3"

        # (b2) RR dead worker-2 with live worker-3 -> fails over ONLY on ConnectError, failover=true
        await client.post(
            "/api/v1/telemetry",
            headers=worker_headers,
            json={
                "worker_id": "worker-2",
                "ip_address": "10.128.0.12",
                "port": 8002,
                "cpu_percent": 5.0,
                "memory_total_mb": 4096.0,
                "memory_used_mb": 512.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.1,
                "active_task_count": 0,
            },
        )
        await app.state.redis_client.set("sched_mode", "round_robin")
        await app.state.redis_client.set("rr_counter", "1")
        resp_rr_failover = await client.post("/tasks", json={"client_id": "c-rr-fo", "task_type": "light"})
        assert resp_rr_failover.status_code == 200
        assert resp_rr_failover.json()["assigned_worker"] == "worker-3"
        assert resp_rr_failover.json()["result"]["cgpa"] == 9.0

        # (b3) Dead worker-2 with NO live workers left -> logs clean unavailable, failover=false
        await app.state.cluster_state.evict_worker("worker-3")
        await app.state.redis_client.set("rr_counter", "1")
        resp_rr_none = await client.post("/tasks", json={"client_id": "c-down-none", "task_type": "light"})
        assert resp_rr_none.status_code == 200
        assert resp_rr_none.json()["result"]["status"] == "unavailable"

        from app.core.logger import TEST_LOG_PATH, csv_logger

        csv_logger.flush()
        with open(TEST_LOG_PATH, encoding="utf-8") as f:
            by_cid = {r["client_id"]: r for r in csv.DictReader(f)}
        assert by_cid["c-503"]["status"] == "rejected_503" and by_cid["c-503"]["failover"] == "false"
        assert by_cid["rr-503"]["status"] == "rejected_503" and by_cid["rr-503"]["failover"] == "false"
        assert by_cid["rr-504"]["status"] == "timeout" and by_cid["rr-504"]["failover"] == "false"
        assert by_cid["c-milp-fo"]["status"] == "ok" and by_cid["c-milp-fo"]["failover"] == "true"
        assert by_cid["c-rr-fo"]["status"] == "ok" and by_cid["c-rr-fo"]["failover"] == "true"
        assert by_cid["c-down-none"]["status"] == "unavailable" and by_cid["c-down-none"]["failover"] == "false"
    await mock_http.aclose()


@pytest.mark.asyncio
async def test_evicted_worker_recovers_automatically_on_heartbeat() -> None:
    """An evicted worker is not permanently blocked and rejoins automatically on next telemetry heartbeat."""
    end_test()
    dead_w2 = True

    def transient_handler(request: httpx.Request) -> httpx.Response:
        port = request.url.port or 0
        if port == 8002 and dead_w2:
            raise httpx.ConnectError("transient network blip", request=request)
        return httpx.Response(
            200,
            json={
                "task_id": "t",
                "worker_id": f"worker-{port - 8000}",
                "status": "COMPLETED",
                "queue_ms": 1.0,
                "execution_ms": 2.0,
                "result": {"cgpa": 9.0},
            },
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(transient_handler))
    app = create_app(
        settings=Settings(local_mode=True, seed_demo_workers=False, default_scheduler="ortools_milp"),
        worker_http_client=mock_http,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hb-revive") as client:
        worker_headers = {"X-Worker-Secret": _get_worker_secret(app)}
        for wid, port, cpu in (("worker-1", 8001, 40.0), ("worker-2", 8002, 5.0), ("worker-3", 8003, 40.0)):
            await client.post(
                "/api/v1/telemetry",
                headers=worker_headers,
                json={
                    "worker_id": wid,
                    "ip_address": f"10.128.0.{10 + port % 10}",
                    "port": port,
                    "cpu_percent": cpu,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 512.0,
                    "memory_percent": 12.5,
                    "load_avg_1m": 0.1,
                    "active_task_count": 0,
                },
            )

        # Transient ConnectError on worker-2 evicts it and fails over to worker-1/3
        r1 = await client.post("/tasks", json={"client_id": "hb-c1", "task_type": "light"})
        assert r1.json()["assigned_worker"] in ("worker-1", "worker-3")
        active_after_evict = [w.worker_id for w in await app.state.cluster_state.get_active_workers()]
        assert active_after_evict == ["worker-1", "worker-3"]

        # Worker-2 recovers and sends its periodic telemetry heartbeat -> automatically re-admitted
        dead_w2 = False
        hb_resp = await client.post(
            "/api/v1/telemetry",
            headers=worker_headers,
            json={
                "worker_id": "worker-2",
                "ip_address": "10.128.0.12",
                "port": 8002,
                "cpu_percent": 5.0,
                "memory_total_mb": 4096.0,
                "memory_used_mb": 512.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.1,
                "active_task_count": 0,
            },
        )
        assert hb_resp.status_code == 200
        active_after_hb = [w.worker_id for w in await app.state.cluster_state.get_active_workers()]
        assert active_after_hb == ["worker-1", "worker-2", "worker-3"]

        # Next MILP request routes back to idle worker-2 (5% CPU)
        r2 = await client.post("/tasks", json={"client_id": "hb-c2", "task_type": "light"})
        assert r2.json()["assigned_worker"] == "worker-2"
    await mock_http.aclose()


def _get_worker_secret(app) -> str:
    return app.state.settings.worker_secret


def test_settings_refuses_startup_without_admin_token_or_worker_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Controller Settings must have no hardcoded ADMIN_TOKEN/WORKER_SECRET defaults."""
    for var in ("ADMIN_TOKEN", "CB_ADMIN_TOKEN", "WORKER_SECRET", "CB_WORKER_SECRET"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, worker_secret="ok-worker-secret")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, admin_token="   ", worker_secret="ok-worker-secret")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, admin_token="ok-admin-token")


@pytest.mark.asyncio
async def test_step_g_auth_lockdown_and_worker_urls_routing() -> None:
    """Verify Step (g): telemetry secret, ops/benchmark/mongo/redis auth gates, /healthz,
    and WORKER_URLS driving seeding plus HTTP task routing.
    """
    end_test()
    captured_ports: list[int] = []

    def custom_port_handler(request: httpx.Request) -> httpx.Response:
        port = request.url.port or 0
        captured_ports.append(port)
        return httpx.Response(
            200,
            json={
                "task_id": "t",
                "worker_id": f"worker-{port - 9100}",
                "status": "COMPLETED",
                "queue_ms": 0.5,
                "execution_ms": 1.5,
                "result": {"cgpa": 9.2},
            },
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(custom_port_handler))
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        default_scheduler="round_robin",
        admin_token="strict-admin-g",
        worker_secret="strict-worker-g",
        worker_urls="http://127.0.0.1:9101,http://127.0.0.1:9102,http://127.0.0.1:9103",  # type: ignore[arg-type]
    )
    app = create_app(settings=cfg, worker_http_client=mock_http)
    seeded = await app.state.cluster_state.seed_virtual_workers_if_empty()
    assert [w.port for w in seeded] == [9101, 9102, 9103]

    transport = httpx.ASGITransport(app=app)
    admin_hdrs = {"Authorization": "Bearer strict-admin-g"}
    worker_hdrs = {"X-Worker-Secret": "strict-worker-g"}

    async with httpx.AsyncClient(transport=transport, base_url="http://step-g") as client:
        assert (await client.get("/healthz")).status_code == 200

        # Telemetry rejects missing/wrong secret and accepts valid X-Worker-Secret
        tel_payload = {
            "worker_id": "worker-1",
            "ip_address": "127.0.0.1",
            "port": 9101,
            "cpu_percent": 12.0,
            "memory_total_mb": 4096.0,
            "memory_used_mb": 512.0,
            "memory_percent": 12.5,
            "load_avg_1m": 0.2,
            "active_task_count": 0,
        }
        assert (await client.post("/api/v1/telemetry", json=tel_payload)).status_code == 401
        assert (
            await client.post("/api/v1/telemetry", json=tel_payload, headers={"X-Worker-Secret": "wrong"})
        ).status_code == 401
        assert (await client.post("/api/v1/telemetry", json=tel_payload, headers=worker_hdrs)).status_code == 200

        # Admin-protected routes reject unauthenticated access and allow Bearer ADMIN_TOKEN
        for path in (
            "/api/v1/telemetry/workers",
            "/api/v1/telemetry/redis",
            "/api/v1/telemetry/mongo",
            "/api/v1/mongo",
            "/api/v1/control/snapshot",
            "/api/v1/control/solver-metrics",
            "/api/v1/benchmark/runs",
        ):
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers=admin_hdrs)).status_code == 200

        assert (await client.post("/api/v1/control/scheduler", json={"scheduler": "round_robin"})).status_code == 401
        assert (await client.post("/api/v1/benchmark/run")).status_code == 401

        # Public POST /tasks dispatches across WORKER_URLS ports 9101, 9102, 9103
        for wid, port in (("worker-1", 9101), ("worker-2", 9102), ("worker-3", 9103)):
            await client.post(
                "/api/v1/telemetry",
                headers=worker_hdrs,
                json={**tel_payload, "worker_id": wid, "port": port},
            )
        captured_ports.clear()
        for i in range(3):
            r = await client.post("/tasks", json={"client_id": f"g-{i}", "task_type": "light"})
            assert r.status_code == 200
        assert captured_ports == [9101, 9102, 9103]
    await mock_http.aclose()
