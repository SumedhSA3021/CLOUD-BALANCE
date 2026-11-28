"""Abstract Scheduler Base Class and In-Flight Resource Reservation Tracker."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from app.models.schemas import SchedulerDecisionMeta, Task, Telemetry


@dataclass(frozen=True, slots=True)
class InFlightReservation:
    """Immutable record of a task dispatched to a worker whose load is not yet in telemetry."""

    task_id: str
    worker_id: str
    cpu_demand_pct: float
    mem_demand_mb: float
    duration_sec: float
    created_at_mono: float
    expires_at_mono: float

    def decay_factor(self, now_mono: float) -> float:
        """Compute linear decay weight in [0.0, 1.0] based on remaining duration."""
        if now_mono >= self.expires_at_mono:
            return 0.0
        if self.duration_sec <= 0.0:
            return 0.0
        remaining = self.expires_at_mono - now_mono
        return max(0.0, min(1.0, remaining / self.duration_sec))


class InFlightTracker:
    """Tracks in-flight task reservations per worker with time-based decay."""

    def __init__(self) -> None:
        self._reservations: dict[str, InFlightReservation] = {}

    def _prune(self, now_mono: float) -> None:
        expired = [
            tid
            for tid, res in self._reservations.items()
            if res.expires_at_mono <= now_mono
        ]
        for tid in expired:
            self._reservations.pop(tid, None)

    def reserve(
        self,
        task: Task,
        worker_id: str,
        now_mono: float | None = None,
    ) -> InFlightReservation:
        """Record an in-flight reservation for `task` on `worker_id`."""
        now = now_mono if now_mono is not None else time.monotonic()
        self._prune(now)
        reservation = InFlightReservation(
            task_id=task.task_id,
            worker_id=worker_id,
            cpu_demand_pct=task.cpu_demand_pct,
            mem_demand_mb=task.mem_demand_mb,
            duration_sec=task.duration_sec,
            created_at_mono=now,
            expires_at_mono=now + max(0.2, task.duration_sec),
        )
        self._reservations[task.task_id] = reservation
        return reservation

    def release(self, task_id: str) -> None:
        """Remove a reservation when a task completes or fails early."""
        self._reservations.pop(task_id, None)

    def release_worker(self, worker_id: str) -> None:
        """Remove in-flight reservations for `worker_id` once reflected in live worker telemetry."""
        to_remove = [
            tid for tid, res in self._reservations.items() if res.worker_id == worker_id
        ]
        for tid in to_remove:
            self._reservations.pop(tid, None)

    def clear(self) -> None:
        """Clear all reservations."""
        self._reservations.clear()

    def get_worker_in_flight(
        self,
        worker_id: str,
        now_mono: float | None = None,
    ) -> tuple[float, float, int]:
        """Return `(decayed_cpu_pct, decayed_mem_mb, active_in_flight_count)` for `worker_id`."""
        now = now_mono if now_mono is not None else time.monotonic()
        self._prune(now)
        cpu_sum = 0.0
        mem_sum = 0.0
        count = 0
        for res in self._reservations.values():
            if res.worker_id == worker_id:
                weight = res.decay_factor(now)
                if weight > 0.0:
                    cpu_sum += res.cpu_demand_pct * weight
                    mem_sum += res.mem_demand_mb * weight
                    count += 1
        return round(cpu_sum, 3), round(mem_sum, 3), count


@dataclass(frozen=True, slots=True)
class BatchAssignmentResult:
    """Result of assigning a micro-batch of tasks across active workers.

    Supports both attribute access (`.assignments`, `.meta`) and tuple unpacking
    (`assignments, meta = scheduler.assign(batch, workers)`).
    """

    assignments: dict[str, str]
    meta: SchedulerDecisionMeta

    def __iter__(self) -> Iterator[Any]:
        yield self.assignments
        yield self.meta


class BaseScheduler(ABC):
    """Abstract interface for all CloudBalance task schedulers."""

    def __init__(
        self,
        name: str,
        in_flight_tracker: InFlightTracker | None = None,
    ) -> None:
        self.name = name
        self.in_flight = in_flight_tracker if in_flight_tracker is not None else InFlightTracker()

    @abstractmethod
    def assign(
        self,
        batch: Sequence[Task],
        workers: Sequence[Telemetry],
        record_in_flight: bool = True,
    ) -> BatchAssignmentResult:
        """Assign each task in `batch` to a worker in `workers`.

        Args:
            batch: Micro-batch of tasks waiting for placement.
            workers: Live worker telemetry snapshots from Redis.
            record_in_flight: Whether to immediately register in-flight reservations.

        Returns:
            BatchAssignmentResult containing `{task_id: worker_id}` and `SchedulerDecisionMeta`.
        """

