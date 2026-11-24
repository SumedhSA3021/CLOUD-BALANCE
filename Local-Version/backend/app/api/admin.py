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
import os
import time
import uuid
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.logger import (
    TEST_LOG_PATH,
    TEST_SUMMARY_COLUMNS,
    TEST_SUMMARY_PATH,
    csv_logger,
    write_test_summary,
)
from app.core.logging import get_logger
from app.schedulers.test_hooks import (
    ModeLockedError,
    end_test,
    is_test_running,
    start_test,
)

logger = get_logger("api.admin")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "cb-admin-secret-2026")

admin_router = APIRouter(prefix="/admin", tags=["admin"])
public_test_router = APIRouter(tags=["test-status"])


class TestState(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    RUNNING = "running"
    DRAINING = "draining"


class StartTestRequest(BaseModel):
    """Payload for POST /admin/test/start."""

    model_config = ConfigDict(extra="ignore")

    mode: str = Field(..., description="'round_robin' or 'milp'")
    duration_s: float = Field(default=30.0, gt=0.0)
    lambda_per_client: float = Field(default=5.0, gt=0.0)
    heavy_ratio: float = Field(default=0.2, ge=0.0, le=1.0)
    seed: int = Field(default=42)


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
        self._lifecycle_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

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
        }

    async def start(
        self,
        req: StartTestRequest,
        app_state: Any,
    ) -> dict[str, Any]:
        async with self._lock:
            if self.state != TestState.IDLE or is_test_running():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Another test is already active in state '{self.state.value}'. Only one test at a time.",
                )

            self.test_id = f"test-{uuid.uuid4().hex[:8]}"
            self.mode = req.mode.lower().strip()
            self.duration_s = float(req.duration_s)
            self.lambda_per_client = float(req.lambda_per_client)
            self.heavy_ratio = float(req.heavy_ratio)
            self.seed = int(req.seed)
            self.start_at = round(time.time() + 5.0, 3)
            self.state = TestState.ARMED

            # Call A3 hook: initialize test under mode lock
            redis_client = getattr(app_state, "redis_client", None)
            in_flight = getattr(app_state, "in_flight_tracker", None)
            start_test(
                mode=self.mode,
                redis_client=redis_client,
                in_flight_tracker=in_flight,
                test_id=self.test_id,
                metadata={
                    "mode": self.mode,
                    "duration_s": self.duration_s,
                    "lambda_per_client": self.lambda_per_client,
                    "heavy_ratio": self.heavy_ratio,
                    "seed": self.seed,
                },
            )

            # Spawn lifecycle worker
            self._lifecycle_task = asyncio.create_task(self._run_lifecycle(app_state))
            return self.get_status()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if self.state == TestState.IDLE:
                return self.get_status()

            if self._lifecycle_task and not self._lifecycle_task.done():
                self._lifecycle_task.cancel()

            self._finalize()
            return self.get_status()

    async def _run_lifecycle(self, app_state: Any) -> None:
        try:
            # 1. Armed -> Wait until start_at
            now = time.time()
            wait_to_start = max(0.0, (self.start_at or now) - now)
            if wait_to_start > 0:
                await asyncio.sleep(wait_to_start)

            # 2. Running
            self.state = TestState.RUNNING
            logger.info("test_lifecycle_running", test_id=self.test_id, mode=self.mode)
            dur = self.duration_s or 30.0
            await asyncio.sleep(dur)

            # 3. Draining: wait up to 15s for in-flight tasks
            self.state = TestState.DRAINING
            logger.info("test_lifecycle_draining", test_id=self.test_id)
            drain_deadline = time.time() + 15.0
            in_flight = getattr(app_state, "in_flight_tracker", None)

            while time.time() < drain_deadline:
                active = 0
                if in_flight is not None:
                    for w in ("worker-1", "worker-2", "worker-3"):
                        active += in_flight.get_count(w)
                if active == 0:
                    break
                await asyncio.sleep(0.2)

        except asyncio.CancelledError:
            pass
        finally:
            self._finalize()

    def _finalize(self) -> None:
        """Write summary row to test_summary.csv and transition back to idle."""
        if self.test_id:
            try:
                write_test_summary(
                    test_id=self.test_id,
                    mode=self.mode or "milp",
                    seed=self.seed or 0,
                    duration_s=self.duration_s or 0.0,
                    lambda_per_client=self.lambda_per_client or 0.0,
                    heavy_ratio=self.heavy_ratio or 0.0,
                )
            except Exception as e:
                logger.error("test_summary_write_error", error=str(e))

        end_test()
        self.state = TestState.IDLE
        self.test_id = None
        self.mode = None
        self.start_at = None
        self.duration_s = None
        self.seed = None
        self.lambda_per_client = None
        self.heavy_ratio = None
        self._lifecycle_task = None


test_manager = ActiveTestManager()


def verify_admin_token(authorization: str | None = Header(default=None)) -> None:
    """Validate Bearer token against configured ADMIN_TOKEN."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin bearer token",
        )


@admin_router.post("/test/start", response_model=TestStatusResponse)
async def admin_start_test(
    payload: StartTestRequest,
    request: Request,
    _auth: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Start an automated benchmark test (armed -> running -> draining -> idle)."""
    return await test_manager.start(payload, request.app.state)


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


# Also mount under /admin/test/status for convenience
@admin_router.get("/test/status", response_model=TestStatusResponse)
async def admin_get_test_status() -> dict[str, Any]:
    return test_manager.get_status()


# --- C4: Summary and Stats Endpoints ---


@admin_router.get("/stats/summary")
async def get_stats_summary(
    _auth: None = Depends(verify_admin_token),
) -> list[dict[str, Any]]:
    """Return all rows from data/test_summary.csv."""
    csv_logger.flush()
    if not TEST_SUMMARY_PATH.exists():
        return []
    with open(TEST_SUMMARY_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


@admin_router.get("/stats/download")
async def download_stats_summary(
    file: str = Query(default="summary", description="'summary' or 'log'"),
    _auth: None = Depends(verify_admin_token),
) -> FileResponse:
    """Download data/test_summary.csv or data/test_log.csv."""
    csv_logger.flush()
    if file.lower() == "log":
        target_path = TEST_LOG_PATH
        filename = "test_log.csv"
        cols = csv_logger._log_columns
    else:
        target_path = TEST_SUMMARY_PATH
        filename = "test_summary.csv"
        cols = TEST_SUMMARY_COLUMNS

    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols if isinstance(cols, list) else cols)

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
    """Reset data/test_summary.csv and data/test_log.csv."""
    csv_logger.flush()

    for p, cols in ((TEST_LOG_PATH, csv_logger._log_path), (TEST_SUMMARY_PATH, TEST_SUMMARY_COLUMNS)):
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols if isinstance(cols, list) else cols)

    return {"status": "reset", "detail": "Test logs and summaries cleared"}
