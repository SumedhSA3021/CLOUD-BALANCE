"""Pluggable Schedulers Registry."""

from app.schedulers.base import (
    BaseScheduler,
    BatchAssignmentResult,
    InFlightReservation,
    InFlightTracker,
)
from app.schedulers.least_connections import LeastConnectionsScheduler
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.schedulers.round_robin import RoundRobinScheduler
from app.schedulers.test_hooks import (
    ModeLockedError,
    check_mode_change_allowed,
    end_test,
    get_current_test_id,
    get_current_test_metadata,
    is_test_running,
    start_test,
)

__all__ = [
    "BaseScheduler",
    "BatchAssignmentResult",
    "InFlightReservation",
    "InFlightTracker",
    "LeastConnectionsScheduler",
    "ModeLockedError",
    "ORToolsMILPScheduler",
    "RoundRobinScheduler",
    "check_mode_change_allowed",
    "end_test",
    "get_current_test_id",
    "get_current_test_metadata",
    "is_test_running",
    "start_test",
]

