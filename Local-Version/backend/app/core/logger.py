"""CSV Logger and Summary Engine for Automated Test Execution (C3 & C4).

Contract:
- Single-writer buffered append to data/test_log.csv with exact contract columns.
- Non-blocking in-memory queue with background disk writer.
- At test end, appends ONE row to data/test_summary.csv with performance percentiles and busy_time_stddev.
"""

from __future__ import annotations

import csv
import os
import queue
import statistics
import threading
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
TEST_LOG_PATH = DATA_DIR / "test_log.csv"
TEST_SUMMARY_PATH = DATA_DIR / "test_summary.csv"

TEST_LOG_COLUMNS: list[str] = [
    "test_id",
    "mode",
    "seed",
    "duration_s",
    "lambda_per_client",
    "heavy_ratio",
    "client_id",
    "task_id",
    "task_type",
    "sent_at",
    "scheduler_used",
    "dispatch_seq",
    "assigned_worker",
    "worker_inflight_at_dispatch",
    "worker_cpu_pct_at_dispatch",
    "queue_ms",
    "exec_ms",
    "total_ms",
    "status",
]

TEST_SUMMARY_COLUMNS: list[str] = [
    "test_id",
    "mode",
    "seed",
    "duration_s",
    "lambda_per_client",
    "heavy_ratio",
    "requests",
    "failed",
    "avg_ms",
    "p50_ms",
    "p95_ms",
    "max_ms",
    "max_queue_ms",
    "throughput_rps",
    "worker1_busy_ms",
    "worker2_busy_ms",
    "worker3_busy_ms",
    "busy_time_stddev",
]


class CSVTaskLogger:
    """Thread-safe, non-blocking single-writer CSV logger for task telemetry."""

    def __init__(self, log_path: Path = TEST_LOG_PATH) -> None:
        self._log_path = log_path
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=100000)
        self._shutdown_event = threading.Event()
        self._lock = threading.RLock()
        self._ensure_file_header()

        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="csv-task-logger")
        self._thread.start()

    def _ensure_file_header(self) -> None:
        """Create directory and write header if file is empty or new."""
        with self._lock:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            if not self._log_path.exists() or self._log_path.stat().st_size == 0:
                with open(self._log_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(TEST_LOG_COLUMNS)

    def _writer_loop(self) -> None:
        """Single-writer consumer draining queue and writing to disk."""
        batch: list[dict[str, Any]] = []
        while not self._shutdown_event.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.2)
                if item is None:
                    # Sentinel received
                    self._queue.task_done()
                    break
                batch.append(item)
                # Drain up to 200 items per disk write
                while len(batch) < 200:
                    try:
                        next_item = self._queue.get_nowait()
                        if next_item is None:
                            self._queue.task_done()
                            break
                        batch.append(next_item)
                    except queue.Empty:
                        break
            except queue.Empty:
                item = None

            if batch:
                try:
                    with self._lock:
                        self._ensure_file_header()
                        with open(self._log_path, "a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=TEST_LOG_COLUMNS, extrasaction="ignore")
                            for row in batch:
                                # Format floats cleanly
                                formatted = {
                                    k: (
                                        f"{v:.2f}"
                                        if isinstance(v, float) and k in ("queue_ms", "exec_ms", "total_ms", "worker_cpu_pct_at_dispatch")
                                        else str(v)
                                    )
                                    for k, v in row.items()
                                }
                                writer.writerow(formatted)
                            f.flush()
                except Exception as err:
                    print(f"[!] CSV writer error: {err}")
                finally:
                    for _ in range(len(batch)):
                        try:
                            self._queue.task_done()
                        except ValueError:
                            pass
                    batch.clear()

    def log_task(self, record: dict[str, Any]) -> None:
        """Asynchronously enqueue a task log record without slowing down dispatch."""
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            # Drop or write synchronously if queue exhausted under extreme burst
            pass

    def flush(self, timeout: float = 3.0) -> None:
        """Wait until all queued records are written to disk, with safety timeout."""
        deadline = time.time() + timeout
        while self._queue.unfinished_tasks > 0 and time.time() < deadline:
            time.sleep(0.01)

    def close(self) -> None:
        """Flush and stop background writer thread."""
        self._shutdown_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=3.0)


# Module-level singleton
csv_logger = CSVTaskLogger()


def log_task_record(
    test_id: str,
    mode: str,
    seed: int | str,
    duration_s: float | int | str,
    lambda_per_client: float | str,
    heavy_ratio: float | str,
    client_id: str,
    task_id: str,
    task_type: str,
    sent_at: float | str,
    scheduler_used: str,
    dispatch_seq: int | str,
    assigned_worker: str,
    worker_inflight_at_dispatch: int | str,
    worker_cpu_pct_at_dispatch: float | str,
    queue_ms: float,
    exec_ms: float,
    total_ms: float,
    status: str,
) -> None:
    """Convenience helper to append a task record to test_log.csv."""
    row = {
        "test_id": test_id,
        "mode": mode,
        "seed": seed,
        "duration_s": duration_s,
        "lambda_per_client": lambda_per_client,
        "heavy_ratio": heavy_ratio,
        "client_id": client_id,
        "task_id": task_id,
        "task_type": task_type,
        "sent_at": sent_at,
        "scheduler_used": scheduler_used,
        "dispatch_seq": dispatch_seq,
        "assigned_worker": assigned_worker,
        "worker_inflight_at_dispatch": worker_inflight_at_dispatch,
        "worker_cpu_pct_at_dispatch": worker_cpu_pct_at_dispatch,
        "queue_ms": queue_ms,
        "exec_ms": exec_ms,
        "total_ms": total_ms,
        "status": status,
    }
    csv_logger.log_task(row)


def write_test_summary(
    test_id: str,
    mode: str,
    seed: int | str,
    duration_s: float,
    lambda_per_client: float,
    heavy_ratio: float,
    log_path: Path = TEST_LOG_PATH,
    summary_path: Path = TEST_SUMMARY_PATH,
) -> dict[str, Any]:
    """Read test_log.csv for test_id, compute performance metrics, and append to test_summary.csv."""
    csv_logger.flush()

    matching_rows: list[dict[str, str]] = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("test_id") == test_id:
                    matching_rows.append(row)

    total_requests = len(matching_rows)
    failed_count = sum(1 for r in matching_rows if r.get("status") != "ok")

    if total_requests > 0:
        total_ms_list = [float(r["total_ms"]) for r in matching_rows if r.get("total_ms")]
        queue_ms_list = [float(r["queue_ms"]) for r in matching_rows if r.get("queue_ms")]

        avg_ms = round(statistics.mean(total_ms_list), 2) if total_ms_list else 0.0
        sorted_totals = sorted(total_ms_list) if total_ms_list else [0.0]

        # Calculate p50 and p95
        def _percentile(data: list[float], p: float) -> float:
            if not data:
                return 0.0
            idx = int(round((len(data) - 1) * p))
            return round(data[idx], 2)

        p50_ms = _percentile(sorted_totals, 0.50)
        p95_ms = _percentile(sorted_totals, 0.95)
        max_ms = round(max(total_ms_list), 2) if total_ms_list else 0.0
        max_queue_ms = round(max(queue_ms_list), 2) if queue_ms_list else 0.0

        dur = float(duration_s) if float(duration_s) > 0.0 else 1.0
        throughput_rps = round(total_requests / dur, 2)

        # Worker busy times: sum of exec_ms per worker (only ok tasks)
        w1_busy = sum(
            float(r["exec_ms"])
            for r in matching_rows
            if r.get("assigned_worker") == "worker-1" and r.get("status") == "ok" and r.get("exec_ms")
        )
        w2_busy = sum(
            float(r["exec_ms"])
            for r in matching_rows
            if r.get("assigned_worker") == "worker-2" and r.get("status") == "ok" and r.get("exec_ms")
        )
        w3_busy = sum(
            float(r["exec_ms"])
            for r in matching_rows
            if r.get("assigned_worker") == "worker-3" and r.get("status") == "ok" and r.get("exec_ms")
        )

        busy_list = [w1_busy, w2_busy, w3_busy]
        # Standard deviation of worker busy times (population std dev)
        busy_stddev = round(statistics.pstdev(busy_list), 2)
    else:
        avg_ms = p50_ms = p95_ms = max_ms = max_queue_ms = throughput_rps = 0.0
        w1_busy = w2_busy = w3_busy = busy_stddev = 0.0

    summary_row = {
        "test_id": test_id,
        "mode": mode,
        "seed": seed,
        "duration_s": duration_s,
        "lambda_per_client": lambda_per_client,
        "heavy_ratio": heavy_ratio,
        "requests": total_requests,
        "failed": failed_count,
        "avg_ms": avg_ms,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "max_ms": max_ms,
        "max_queue_ms": max_queue_ms,
        "throughput_rps": throughput_rps,
        "worker1_busy_ms": round(w1_busy, 2),
        "worker2_busy_ms": round(w2_busy, 2),
        "worker3_busy_ms": round(w3_busy, 2),
        "busy_time_stddev": busy_stddev,
    }

    # Append to data/test_summary.csv
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not summary_path.exists() or summary_path.stat().st_size == 0
    with open(summary_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEST_SUMMARY_COLUMNS)
        if write_header:
            writer.writerow({c: c for c in TEST_SUMMARY_COLUMNS})
        writer.writerow(summary_row)

    return summary_row
