"""Mode Lock and Test Reset Hooks (A3).

Contract Requirements:
- start_test(mode): set sched_mode, rr_counter = 0, zero all in-flight counters, reset solver_call_count.
- Reject mode changes while a test is running (raise an error the API turns into HTTP 409).
- Expose start_test, end_test, is_test_running as plain functions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.redis_client import DualRedisClient
from app.schedulers.base import InFlightTracker
from app.schedulers.ortools_milp import reset_solver_call_count

_TEST_RUNNING: bool = False
_TEST_MODE: str | None = None
_TEST_ID: str | None = None
_TEST_METADATA: dict[str, Any] = {}

WORKERS = ("worker-1", "worker-2", "worker-3")


class ModeLockedError(Exception):
    """Raised when an attempt is made to change the scheduling mode while a test is running."""

    pass


def is_test_running() -> bool:
    """Return True if an automated benchmark/test is currently in progress."""
    return _TEST_RUNNING


def get_current_test_id() -> str:
    """Return active test_id or 'none' if running outside a test."""
    return _TEST_ID if _TEST_ID else "none"


def get_current_test_metadata() -> dict[str, Any]:
    """Return dictionary of current test parameters or empty dict."""
    return dict(_TEST_METADATA)


def check_mode_change_allowed() -> None:
    """Raise ModeLockedError if a test is currently running."""
    if _TEST_RUNNING:
        raise ModeLockedError("Cannot change scheduling mode while a test is running")


async def reset_redis_test_keys(redis_client: DualRedisClient, mode: str) -> None:
    """Set sched_mode, rr_counter = 0, and zero all in-flight counters in Redis."""
    await redis_client.set("sched_mode", mode)
    await redis_client.set("rr_counter", "0")
    for w in WORKERS:
        await redis_client.set(f"inflight:{w}", "0")
        await redis_client.set(f"cluster:inflight:{w}", "0")


def start_test(
    mode: str,
    redis_client: DualRedisClient | None = None,
    in_flight_tracker: InFlightTracker | None = None,
    test_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Initialize a test run under the mode lock.

    - Sets sched_mode
    - Resets rr_counter = 0
    - Zeroes in-flight counters
    - Resets solver_call_count
    """
    global _TEST_RUNNING, _TEST_MODE, _TEST_ID, _TEST_METADATA

    if _TEST_RUNNING:
        raise ModeLockedError("Cannot start test: another test is currently running")

    normalized_mode = mode.lower().strip()
    _TEST_RUNNING = True
    _TEST_MODE = normalized_mode
    _TEST_ID = test_id
    _TEST_METADATA = metadata or {}

    # 1. Reset OR-Tools solver call count
    reset_solver_call_count()

    # 2. Reset InFlightTracker in-memory
    if in_flight_tracker is not None:
        in_flight_tracker.clear()

    # 3. Reset Redis keys: sched_mode, rr_counter = 0, inflight per worker = 0
    if redis_client is not None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(reset_redis_test_keys(redis_client, normalized_mode))
        except RuntimeError:
            asyncio.run(reset_redis_test_keys(redis_client, normalized_mode))


def end_test() -> None:
    """Mark test finished and release the mode lock."""
    global _TEST_RUNNING, _TEST_MODE, _TEST_ID, _TEST_METADATA
    _TEST_RUNNING = False
    _TEST_MODE = None
    _TEST_ID = None
    _TEST_METADATA = {}
