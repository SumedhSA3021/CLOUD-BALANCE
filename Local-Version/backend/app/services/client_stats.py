"""Per-Client Telemetry Tracker (arrival rate req/s, queue depth, worker affinity)."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from app.models.schemas import ClientStats


@dataclass
class _ClientRecord:
    """Internal mutable state for a single client laptop."""

    client_id: str
    arrival_timestamps: deque[float] = field(default_factory=deque)
    queued_count: int = 0
    total_sent: int = 0
    wait_samples_ms: deque[float] = field(default_factory=lambda: deque(maxlen=50))
    served_by: dict[str, int] = field(default_factory=dict)


class ClientStatsService:
    """Tracks live request rates, queue wait times, and worker distribution per client_id."""

    def __init__(self, window_sec: float = 10.0) -> None:
        self._window_sec = window_sec
        self._clients: dict[str, _ClientRecord] = {}
        self._global_arrivals: deque[float] = deque()

    def _prune_timestamps(self, q: deque[float], now: float) -> None:
        cutoff = now - self._window_sec
        while q and q[0] < cutoff:
            q.popleft()

    def record_enqueue(self, client_id: str, now_mono: float | None = None) -> None:
        """Record a task arrival from `client_id`."""
        now = now_mono if now_mono is not None else time.monotonic()
        rec = self._clients.get(client_id)
        if rec is None:
            rec = _ClientRecord(client_id=client_id)
            self._clients[client_id] = rec

        rec.arrival_timestamps.append(now)
        rec.queued_count += 1
        rec.total_sent += 1
        self._global_arrivals.append(now)
        self._prune_timestamps(rec.arrival_timestamps, now)
        self._prune_timestamps(self._global_arrivals, now)

    def record_assigned(
        self,
        client_id: str,
        worker_id: str,
        queue_wait_ms: float,
    ) -> None:
        """Record that a queued task from `client_id` was assigned to `worker_id`."""
        rec = self._clients.get(client_id)
        if rec is None:
            rec = _ClientRecord(client_id=client_id)
            self._clients[client_id] = rec

        rec.queued_count = max(0, rec.queued_count - 1)
        rec.wait_samples_ms.append(max(0.0, queue_wait_ms))
        rec.served_by[worker_id] = rec.served_by.get(worker_id, 0) + 1

    def record_dropped(self, client_id: str) -> None:
        """Decrement queued count if a task could not be assigned."""
        rec = self._clients.get(client_id)
        if rec is not None:
            rec.queued_count = max(0, rec.queued_count - 1)

    def get_lambda_total(self, now_mono: float | None = None) -> float:
        """Compute total cluster arrival rate (req/sec) across all clients."""
        now = now_mono if now_mono is not None else time.monotonic()
        self._prune_timestamps(self._global_arrivals, now)
        return round(len(self._global_arrivals) / self._window_sec, 2)

    def get_client_stats(self, now_mono: float | None = None) -> list[ClientStats]:
        """Return sorted list of ClientStats for all known clients."""
        now = now_mono if now_mono is not None else time.monotonic()
        stats: list[ClientStats] = []
        for client_id in sorted(self._clients.keys()):
            rec = self._clients[client_id]
            self._prune_timestamps(rec.arrival_timestamps, now)
            rate = round(len(rec.arrival_timestamps) / self._window_sec, 2)
            avg_wait = (
                round(sum(rec.wait_samples_ms) / len(rec.wait_samples_ms), 2)
                if rec.wait_samples_ms
                else 0.0
            )
            stats.append(
                ClientStats(
                    client_id=client_id,
                    req_per_sec=rate,
                    queued=rec.queued_count,
                    total_sent=rec.total_sent,
                    avg_queue_wait_ms=avg_wait,
                    served_by=dict(rec.served_by),
                )
            )
        return stats

