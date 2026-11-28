"""Admin Test Lifecycle and Stats API Endpoints (C2 & C4).

Endpoints:
- POST /admin/test/start (Bearer ADMIN_TOKEN)
- POST /admin/test/stop (Bearer ADMIN_TOKEN)
- GET /test/status (Public)
- GET /admin/stats/summary (Bearer ADMIN_TOKEN)
- GET /admin/stats/download (Bearer ADMIN_TOKEN)
- POST /admin/stats/reset (Bearer ADMIN_TOKEN)
"""

from __future__ import annotations

import asyncio
import csv
import secrets
import time
import uuid
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.logger import (
    TEST_LOG_COLUMNS,
    TEST_LOG_PATH,
    TEST_SUMMARY_COLUMNS,
    TEST_SUMMARY_PATH,
    csv_logger,
    log_task_record,
    write_test_summary,
)
from app.core.logging import get_logger
from app.core.security import resolve_app_settings, verify_admin_token
from app.core.simulator import simulator_manager
from app.schedulers.test_hooks import (
    ModeLockedError,
    end_test,
    is_test_running,
    reset_redis_test_keys,
    start_test,
)

logger = get_logger("api.admin")

admin_router = APIRouter(prefix="/admin", tags=["admin"])
public_test_router = APIRouter(tags=["test-status"])


class TestState(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    RUNNING = "running"
    DRAINING = "draining"


class StartTestRequest(BaseModel):
    """Payload for POST /admin/test/start."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    mode: str = Field(
        ...,
        description="Scheduler test mode: 'round_robin' or 'milp' (accepts 'ortools_milp' alias)",
    )
    duration_s: float = Field(default=60.0, gt=0.0, le=120.0)
    lambda_per_client: float = Field(default=3.0, gt=0.0, le=1000.0)
    heavy_ratio: float = Field(default=0.3, ge=0.0, le=1.0)
    seed: int = Field(default=42)
    load_source: str = Field(default="external", description="'external' or 'simulator'")

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: Any) -> str:
        cleaned = str(v).lower().strip()
        if cleaned in ("round_robin", "rr"):
            return "round_robin"
        if cleaned in ("milp", "ortools_milp"):
            return "milp"
        raise ValueError(f"Unsupported scheduler mode '{v}'. Use 'round_robin' or 'milp'.")

    @field_validator("load_source", mode="before")
    @classmethod
    def validate_load_source(cls, v: Any) -> str:
        cleaned = str(v or "simulator").lower().strip()
        if cleaned not in ("simulator", "external"):
            raise ValueError(f"Unsupported load_source '{v}'. Use 'simulator' or 'external'.")
        return cleaned


class TestStatusResponse(BaseModel):
    """Payload returned by GET /test/status."""

    model_config = ConfigDict(extra="ignore")

    state: str
    test_id: str | None = None
    mode: str | None = None
    start_at: float | None = None
    duration_s: float | None = None
    seed: int | None = None
    lambda_per_client: float | None = None
    heavy_ratio: float | None = None
    load_source: str | None = None
    sent: int | None = 0
    ok: int | None = 0
    failed: int | None = 0


class ActiveTestManager:
    """Manages state transitions: idle -> armed -> running -> draining -> idle."""

    def __init__(self) -> None:
        self.state: TestState = TestState.IDLE
        self.test_id: str | None = None
        self.mode: str | None = None
        self.start_at: float | None = None
        self.duration_s: float | None = None
        self.seed: int | None = None
        self.lambda_per_client: float | None = None
        self.heavy_ratio: float | None = None
        self.load_source: str = "external"
        self.counters: dict[str, int] = {"sent": 0, "ok": 0, "failed": 0}
        self.arming_delay_sec: float = 5.0
        self.drain_timeout_sec: float = 15.0
        self._active_tasks: dict[str, dict[str, Any]] = {}
        self._timed_out_task_ids: set[str] = set()
        self._finalizing_test_id: str | None = None
        self._lifecycle_task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def register_inflight_task(self, task_id: str, entry: dict[str, Any]) -> None:
        """Track an active test request so draining leftovers can log status=timeout."""
        self._active_tasks[task_id] = entry

    def update_inflight_worker(
        self,
        task_id: str,
        assigned_worker: str,
        inflight_count: int,
        worker_cpu_pct: float,
        failover: bool = False,
    ) -> None:
        """Update tracked worker info when failover routes to a live worker."""
        entry = self._active_tasks.get(task_id)
        if entry is not None:
            entry["assigned_worker"] = assigned_worker
            entry["worker_inflight_at_dispatch"] = inflight_count
            entry["worker_cpu_pct_at_dispatch"] = worker_cpu_pct
            entry["failover"] = failover

    def complete_inflight_task(self, task_id: str) -> bool:
        """Mark task complete; return False if drain timeout already logged it as timeout."""
        if task_id in self._timed_out_task_ids:
            self._timed_out_task_ids.discard(task_id)
            return False
        self._active_tasks.pop(task_id, None)
        return True

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    def record_task_result(self, status_code: str) -> None:
        """Record dispatched task outcome for active test counters."""
        if self.state == TestState.IDLE:
            return
        self.counters["sent"] += 1
        st = str(status_code).lower()
        if st == "ok":
            self.counters["ok"] += 1
        else:
            self.counters["failed"] += 1

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "test_id": self.test_id,
            "mode": self.mode,
            "start_at": self.start_at,
            "duration_s": self.duration_s,
            "seed": self.seed,
            "lambda_per_client": self.lambda_per_client,
            "heavy_ratio": self.heavy_ratio,
            "load_source": self.load_source,
            "sent": self.counters["sent"],
            "ok": self.counters["ok"],
            "failed": self.counters["failed"],
        }

    async def start(
        self,
        req: StartTestRequest,
        app_state: Any,
    ) -> dict[str, Any]:
        async with self._get_lock():
            if self.state != TestState.IDLE or is_test_running():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Another test is already active in state '{self.state.value}'. Only one test at a time.",
                )

            resolved_state = getattr(app_state, "state", app_state)
            test_id = f"test-{uuid.uuid4().hex[:8]}"
            mode = req.mode
            duration_s = float(req.duration_s)
            lambda_per_client = float(req.lambda_per_client)
            heavy_ratio = float(req.heavy_ratio)
            seed = int(req.seed)
            load_source = req.load_source
            start_at = round(time.time() + self.arming_delay_sec, 3)

            redis_client = getattr(resolved_state, "redis_client", None)
            in_flight = getattr(resolved_state, "in_flight_tracker", None)
            try:
                start_test(
                    mode=mode,
                    redis_client=redis_client,
                    in_flight_tracker=in_flight,
                    test_id=test_id,
                    metadata={
                        "mode": mode,
                        "duration_s": duration_s,
                        "lambda_per_client": lambda_per_client,
                        "heavy_ratio": heavy_ratio,
                        "seed": seed,
                        "load_source": load_source,
                    },
                )
                if redis_client is not None and not getattr(redis_client, "_using_memory", True):
                    await reset_redis_test_keys(redis_client, mode)
            except ModeLockedError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc

            self.test_id = test_id
            self.mode = mode
            self.duration_s = duration_s
            self.lambda_per_client = lambda_per_client
            self.heavy_ratio = heavy_ratio
            self.seed = seed
            self.load_source = load_source
            self.counters = {"sent": 0, "ok": 0, "failed": 0}
            self._active_tasks.clear()
            self._timed_out_task_ids.clear()
            self.start_at = start_at
            self.state = TestState.ARMED

            # Spawn lifecycle worker
            self._lifecycle_task = asyncio.create_task(self._run_lifecycle(app_state))
            return self.get_status()

    async def stop(self) -> dict[str, Any]:
        async with self._get_lock():
            if self.state == TestState.IDLE:
                return self.get_status()

            # Cancel internal simulator if running
            await simulator_manager.stop()

            task = self._lifecycle_task
            self._lifecycle_task = None
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            await self._finalize_async()
            return self.get_status()

    async def _run_lifecycle(self, app_state: Any) -> None:
        try:
            # 1. Armed -> Wait until start_at
            now = time.time()
            wait_to_start = max(0.0, (self.start_at if self.start_at is not None else now) - now)
            if wait_to_start > 0:
                await asyncio.sleep(wait_to_start)

            # 2. Running
            self.state = TestState.RUNNING
            logger.info("test_lifecycle_running", test_id=self.test_id, mode=self.mode, load_source=self.load_source)
            dur = self.duration_s if self.duration_s is not None else 30.0
            lam = self.lambda_per_client if self.lambda_per_client is not None else 2.0
            hr = self.heavy_ratio if self.heavy_ratio is not None else 0.2
            sd = self.seed if self.seed is not None else 42

            if self.load_source == "simulator":
                # Start built-in simulator
                await simulator_manager.start(
                    app=app_state,
                    duration_s=dur,
                    lambda_per_client=lam,
                    heavy_ratio=hr,
                    seed=sd,
                    start_at=self.start_at if self.start_at is not None else time.time(),
                    num_clients=3,
                    on_result=self.record_task_result,
                )

            await asyncio.sleep(dur)

            # Stop spawning new simulator requests while allowing in-flight tasks to drain
            if self.load_source == "simulator":
                await simulator_manager.stop_spawning()

            # 3. Draining: wait up to 15s (configurable) for in-flight tasks; mark leftovers timeout
            self.state = TestState.DRAINING
            logger.info("test_lifecycle_draining", test_id=self.test_id)
            drain_deadline = time.time() + self.drain_timeout_sec
            resolved_state = getattr(app_state, "state", app_state)
            in_flight = getattr(resolved_state, "in_flight_tracker", None)

            while time.time() < drain_deadline:
                active = len(self._active_tasks)
                if in_flight is not None:
                    for w in ("worker-1", "worker-2", "worker-3"):
                        active += in_flight.get_count(w)
                if active == 0:
                    break
                await asyncio.sleep(0.1)

            if self._active_tasks:
                for leftover_id, entry in list(self._active_tasks.items()):
                    self._active_tasks.pop(leftover_id, None)
                    self._timed_out_task_ids.add(leftover_id)
                    elapsed_ms = round((time.monotonic() - float(entry["start_mono"])) * 1000.0, 2)
                    log_task_record(
                        test_id=str(entry["test_id"]),
                        mode=str(entry["mode"]),
                        seed=entry["seed"],
                        duration_s=entry["duration_s"],
                        lambda_per_client=entry["lambda_per_client"],
                        heavy_ratio=entry["heavy_ratio"],
                        client_id=str(entry["client_id"]),
                        task_id=leftover_id,
                        task_type=str(entry["task_type"]),
                        sent_at=entry["sent_at"],
                        scheduler_used=str(entry["scheduler_used"]),
                        dispatch_seq=entry["dispatch_seq"],
                        assigned_worker=str(entry["assigned_worker"]),
                        worker_inflight_at_dispatch=entry["worker_inflight_at_dispatch"],
                        worker_cpu_pct_at_dispatch=entry["worker_cpu_pct_at_dispatch"],
                        queue_ms=0.0,
                        exec_ms=0.0,
                        total_ms=elapsed_ms,
                        status="timeout",
                        failover=bool(entry.get("failover", False)),
                        client_rate=entry.get("client_rate"),
                        client_task_type=entry.get("client_task_type"),
                    )
                    self.record_task_result("timeout")

            if in_flight is not None:
                in_flight.clear()

        except asyncio.CancelledError:
            pass
        finally:
            await simulator_manager.stop()
            await self._finalize_async()

    def _capture_finalization_snapshot(self) -> tuple[str, str, int | str, float, float, float] | None:
        """Atomically claim active test metadata for summary writing before entering IDLE."""
        if self.state == TestState.IDLE or not self.test_id:
            return None
        if self._finalizing_test_id == self.test_id:
            return None
        self._finalizing_test_id = self.test_id
        return (
            self.test_id,
            self.mode or "milp",
            self.seed if self.seed is not None else 0,
            self.duration_s if self.duration_s is not None else 0.0,
            self.lambda_per_client if self.lambda_per_client is not None else 0.0,
            self.heavy_ratio if self.heavy_ratio is not None else 0.0,
        )

    def _reset_to_idle(self) -> None:
        """Reset manager state to IDLE after summary row is safely persisted."""
        self.state = TestState.IDLE
        self.test_id = None
        self.mode = None
        self.start_at = None
        self.duration_s = None
        self.seed = None
        self.lambda_per_client = None
        self.heavy_ratio = None
        self._finalizing_test_id = None
        self._lifecycle_task = None
        end_test()

    async def _finalize_async(self) -> None:
        """Write summary row BEFORE flipping state to IDLE so callers never race."""
        snap = self._capture_finalization_snapshot()
        try:
            if snap is not None:
                tid, mode, seed, dur, lam, hr = snap
                try:
                    await asyncio.to_thread(
                        write_test_summary,
                        test_id=tid,
                        mode=mode,
                        seed=seed,
                        duration_s=dur,
                        lambda_per_client=lam,
                        heavy_ratio=hr,
                    )
                except Exception as e:
                    logger.error("test_summary_write_error", error=str(e))
        finally:
            self._reset_to_idle()

    def _finalize(self) -> None:
        """Synchronous finalization helper."""
        snap = self._capture_finalization_snapshot()
        try:
            if snap is not None:
                tid, mode, seed, dur, lam, hr = snap
                try:
                    write_test_summary(
                        test_id=tid,
                        mode=mode,
                        seed=seed,
                        duration_s=dur,
                        lambda_per_client=lam,
                        heavy_ratio=hr,
                    )
                except Exception as e:
                    logger.error("test_summary_write_error", error=str(e))
        finally:
            self._reset_to_idle()


test_manager = ActiveTestManager()


class AdminLoginRequest(BaseModel):
    """Payload for POST /admin/auth/login."""

    model_config = ConfigDict(extra="ignore")

    token: str = Field(..., min_length=1)


class AdminAuthResponse(BaseModel):
    """Payload returned by Admin authentication endpoints."""

    authenticated: bool
    role: str = "admin"


@admin_router.post("/auth/login", response_model=AdminAuthResponse)
async def admin_auth_login(payload: AdminLoginRequest, request: Request) -> AdminAuthResponse:
    """Verify Admin bearer token and confirm administrative session access."""
    expected = resolve_app_settings(request).admin_token
    candidate = payload.token.strip()
    if not candidate or not secrets.compare_digest(candidate, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin bearer token",
        )
    return AdminAuthResponse(authenticated=True, role="admin")


@admin_router.get("/auth/verify", response_model=AdminAuthResponse)
async def admin_auth_verify(
    _auth: None = Depends(verify_admin_token),
) -> AdminAuthResponse:
    """Verify currently presented Admin Bearer token."""
    return AdminAuthResponse(authenticated=True, role="admin")


@admin_router.post("/test/start", response_model=TestStatusResponse)
async def admin_start_test(
    payload: StartTestRequest,
    request: Request,
    _auth: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Start an automated benchmark test (armed -> running -> draining -> idle)."""
    return await test_manager.start(payload, request.app)


@admin_router.post("/test/stop", response_model=TestStatusResponse)
async def admin_stop_test(
    _auth: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Stop active benchmark test, drain in-flight, and write summary."""
    return await test_manager.stop()


@public_test_router.get("/test/status", response_model=TestStatusResponse)
async def get_test_status() -> dict[str, Any]:
    """Public status endpoint reporting state, test_id, and benchmark parameters."""
    return test_manager.get_status()


# --- C4: Summary and Stats Endpoints ---


@admin_router.get("/stats/summary")
async def get_stats_summary(
    _auth: None = Depends(verify_admin_token),
) -> list[dict[str, Any]]:
    """Return all rows from data/test_summary.csv."""
    await asyncio.to_thread(csv_logger.flush)
    if not TEST_SUMMARY_PATH.exists():
        return []
    with csv_logger._lock, open(TEST_SUMMARY_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


@admin_router.get("/stats/download")
async def download_stats_summary(
    file: str = Query(default="summary", description="'summary' or 'log'"),
    _auth: None = Depends(verify_admin_token),
) -> FileResponse:
    """Download data/test_summary.csv or data/test_log.csv."""
    await asyncio.to_thread(csv_logger.flush)
    if file.lower() in ("log", "test_log"):
        target_path = TEST_LOG_PATH
        filename = "test_log.csv"
        cols = TEST_LOG_COLUMNS
    else:
        target_path = TEST_SUMMARY_PATH
        filename = "test_summary.csv"
        cols = TEST_SUMMARY_COLUMNS

    if not target_path.exists():
        with csv_logger._lock:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(cols)

    return FileResponse(
        path=str(target_path),
        media_type="text/csv",
        filename=filename,
    )


@admin_router.get("/stats/live")
async def get_live_dispatch_stats(
    _auth: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Return per-worker dispatched counts bucketed by second for last 60s and test totals."""
    from app.core.live_stats import live_dispatch_tracker

    return live_dispatch_tracker.get_live_stats()


@admin_router.post("/stats/reset")
async def reset_stats(
    _auth: None = Depends(verify_admin_token),
) -> dict[str, str]:
    """Reset data/test_summary.csv, data/test_log.csv, and live dispatch counters."""
    if test_manager.state != TestState.IDLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reset stats while a test is active. Stop the running test first.",
        )

    await asyncio.to_thread(csv_logger.reset_logs, TEST_LOG_PATH, TEST_SUMMARY_PATH)

    from app.core.live_stats import live_dispatch_tracker

    live_dispatch_tracker.reset_current_test()
    test_manager.counters = {"sent": 0, "ok": 0, "failed": 0}

    return {"status": "reset", "detail": "Test logs and summaries cleared"}
