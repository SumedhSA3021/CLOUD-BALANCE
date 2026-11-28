"""In-memory live dispatch tracker for the last 60 seconds and current test totals."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

WORKERS = ("worker-1", "worker-2", "worker-3")


class LiveDispatchTracker:
    """Tracks per-worker dispatches bucketed by second for a sliding 60-second window."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        # Mapping: int(timestamp_sec) -> dict(worker_id -> count)
        self._buckets: dict[int, dict[str, int]] = defaultdict(
            lambda: {"worker-1": 0, "worker-2": 0, "worker-3": 0}
        )
        # Cumulative per-worker totals for current test
        self._current_test_totals: dict[str, int] = {
            "worker-1": 0,
            "worker-2": 0,
            "worker-3": 0,
        }

    def record_dispatch(self, worker_id: str) -> None:
        """Record a single task dispatch to a worker at the current wall clock second."""
        if worker_id not in WORKERS:
            return
        sec = int(time.time())
        with self._lock:
            self._buckets[sec][worker_id] += 1
            self._current_test_totals[worker_id] += 1

    def get_worker_cumulative(self, worker_id: str) -> int:
        """Get cumulative task dispatches for a specific worker in the current test."""
        with self._lock:
            return self._current_test_totals.get(worker_id, 0)

    def get_current_test_totals(self) -> dict[str, int]:
        """Return snapshot of cumulative dispatches per worker in current test."""
        with self._lock:
            return dict(self._current_test_totals)

    def reset_current_test(self) -> None:
        """Reset the counters and sliding window when a new test starts."""
        with self._lock:
            self._current_test_totals = {
                "worker-1": 0,
                "worker-2": 0,
                "worker-3": 0,
            }
            self._buckets.clear()

    def get_live_stats(self) -> dict[str, Any]:
        """Return per-worker dispatched counts bucketed by second for the last 60s and test totals."""
        now_sec = int(time.time())
        with self._lock:
            # Prune buckets older than 120s to bound memory
            cutoff = now_sec - 120
            stale_keys = [s for s in self._buckets if s < cutoff]
            for s in stale_keys:
                del self._buckets[s]

            timestamps: list[int] = []
            labels: list[str] = []
            w1_series: list[int] = []
            w2_series: list[int] = []
            w3_series: list[int] = []

            for offset in range(self.window_seconds - 1, -1, -1):
                sec = now_sec - offset
                timestamps.append(sec)
                labels.append(f"-{offset}s" if offset > 0 else "now")
                counts = self._buckets.get(
                    sec, {"worker-1": 0, "worker-2": 0, "worker-3": 0}
                )
                w1_series.append(counts.get("worker-1", 0))
                w2_series.append(counts.get("worker-2", 0))
                w3_series.append(counts.get("worker-3", 0))

            totals = dict(self._current_test_totals)

        return {
            "window_seconds": self.window_seconds,
            "timestamps": timestamps,
            "labels": labels,
            "series": {
                "worker-1": w1_series,
                "worker-2": w2_series,
                "worker-3": w3_series,
            },
            "current_test_totals": totals,
            "total_dispatched": sum(totals.values()),
        }


live_dispatch_tracker = LiveDispatchTracker(window_seconds=60)
