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
import shutil
import statistics
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_TEST_LOG_FILENAME,
    DEFAULT_TEST_SUMMARY_FILENAME,
    ROOT_DIR,
)


def _resolve_data_dir(raw_dir: str | None = None) -> Path:
    if raw_dir is None:
        try:
            from app.core.config import Settings

            raw_dir = Settings().data_dir
        except Exception:
            raw_dir = os.getenv("CB_DATA_DIR") or os.getenv("DATA_DIR") or DEFAULT_DATA_DIR
    val = raw_dir.strip() or DEFAULT_DATA_DIR
    p = Path(val)
    return p if p.is_absolute() else (ROOT_DIR / p)


DATA_DIR = _resolve_data_dir()
TEST_LOG_PATH = DATA_DIR / DEFAULT_TEST_LOG_FILENAME
TEST_SUMMARY_PATH = DATA_DIR / DEFAULT_TEST_SUMMARY_FILENAME

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
    "failover",
    "client_rate",
    "client_task_type",
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
    "clients_seen",
]


def _format_csv_row(row: dict[str, Any]) -> dict[str, str]:
    """Format row dictionary values cleanly for CSV output (None -> empty string)."""
    return {
        k: (
            ""
            if v is None
            else f"{v:.2f}"
            if isinstance(v, float)
            and k in ("queue_ms", "exec_ms", "total_ms", "worker_cpu_pct_at_dispatch")
            else ("true" if v is True else "false" if v is False else str(v))
        )
        for k, v in row.items()
    }


def _ensure_csv_header(
    csv_path: Path,
    columns: list[str],
    defaults: dict[str, str] | None = None,
) -> None:
    """Create parent directory and write or migrate a CSV header without losing existing rows."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)
        return

    with open(csv_path, newline="", encoding="utf-8") as f:
        existing_rows = list(csv.reader(f))

    if not existing_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)
        return

    current_header = existing_rows[0]
    if current_header == columns:
        return

    fallback_defaults = defaults or {}
    tmp_path = csv_path.with_suffix(".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for raw in existing_rows[1:]:
            if not raw:
                continue
            row_map = {
                col: (raw[idx] if idx < len(raw) else "")
                for idx, col in enumerate(current_header)
            }
            for key, default_val in fallback_defaults.items():
                if not row_map.get(key):
                    row_map[key] = default_val
            writer.writerow({col: row_map.get(col, "") for col in columns})
    tmp_path.replace(csv_path)


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
        """Create directory and write or migrate header if missing or outdated."""
        with self._lock:
            _ensure_csv_header(self._log_path, TEST_LOG_COLUMNS, defaults={"failover": "false"})

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
                                writer.writerow(_format_csv_row(row))
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

    def _ensure_writer_alive(self) -> None:
        """Restart background writer thread if closed previously."""
        if not self._thread.is_alive():
            self._shutdown_event.clear()
            self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="csv-task-logger")
            self._thread.start()

    def log_task(self, record: dict[str, Any]) -> None:
        """Asynchronously enqueue a task log record without slowing down dispatch."""
        with self._lock:
            self._ensure_writer_alive()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            # Fallback synchronous write under lock rather than dropping records
            with self._lock:
                self._ensure_file_header()
                with open(self._log_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=TEST_LOG_COLUMNS, extrasaction="ignore")
                    writer.writerow(_format_csv_row(record))

    def flush(self, timeout: float = 3.0) -> None:
        """Wait until all queued records are written to disk, with safety timeout."""
        deadline = time.time() + timeout
        while self._queue.unfinished_tasks > 0 and time.time() < deadline:
            time.sleep(0.01)

    def reset_logs(
        self,
        log_path: Path | None = None,
        summary_path: Path = TEST_SUMMARY_PATH,
    ) -> None:
        """Flush pending records, archive non-empty CSVs with timestamp, and reset fresh headers."""
        self.flush()
        target_log = log_path if log_path is not None else self._log_path
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        with self._lock:
            for p, cols in ((target_log, TEST_LOG_COLUMNS), (summary_path, TEST_SUMMARY_COLUMNS)):
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.exists() and p.stat().st_size > 0:
                    with open(p, encoding="utf-8") as check_f:
                        lines = sum(1 for _ in check_f)
                    if lines > 1:
                        archive_dir = p.parent / "archive"
                        archive_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, archive_dir / f"{p.stem}_{stamp}{p.suffix}")
                with open(p, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(cols)

    def close(self) -> None:
        """Flush and stop background writer thread."""
        self._shutdown_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread.is_alive():
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
    failover: bool | str = False,
    client_rate: float | str | None = None,
    client_task_type: str | None = None,
) -> None:
    """Convenience helper to append a task record to test_log.csv."""
    failover_str = (
        failover.lower()
        if isinstance(failover, str)
        else ("true" if failover else "false")
    )
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
        "failover": failover_str,
        "client_rate": "" if client_rate is None else client_rate,
        "client_task_type": "" if client_task_type is None else client_task_type,
    }
    csv_logger.log_task(row)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert CSV field to finite float."""
    try:
        parsed = float(val)
        return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else default
    except (ValueError, TypeError):
        return default


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
    with csv_logger._lock:
        if log_path.exists():
            with open(log_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("test_id") == test_id:
                        matching_rows.append(row)

    total_requests = len(matching_rows)
    failed_count = sum(1 for r in matching_rows if r.get("status") != "ok")

    if total_requests > 0:
        total_ms_list = [_safe_float(r["total_ms"]) for r in matching_rows if r.get("total_ms")]
        queue_ms_list = [_safe_float(r["queue_ms"]) for r in matching_rows if r.get("queue_ms")]

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
            _safe_float(r["exec_ms"])
            for r in matching_rows
            if r.get("assigned_worker") == "worker-1" and r.get("status") == "ok" and r.get("exec_ms")
        )
        w2_busy = sum(
            _safe_float(r["exec_ms"])
            for r in matching_rows
            if r.get("assigned_worker") == "worker-2" and r.get("status") == "ok" and r.get("exec_ms")
        )
        w3_busy = sum(
            _safe_float(r["exec_ms"])
            for r in matching_rows
            if r.get("assigned_worker") == "worker-3" and r.get("status") == "ok" and r.get("exec_ms")
        )

        busy_list = [w1_busy, w2_busy, w3_busy]
        # Standard deviation of worker busy times (population std dev)
        busy_stddev = round(statistics.pstdev(busy_list), 2)
    else:
        avg_ms = p50_ms = p95_ms = max_ms = max_queue_ms = throughput_rps = 0.0
        w1_busy = w2_busy = w3_busy = busy_stddev = 0.0

    clients_seen = len(
        {str(r.get("client_id", "")).strip() for r in matching_rows if str(r.get("client_id", "")).strip()}
    )

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
        "clients_seen": clients_seen,
    }

    # Append to data/test_summary.csv under lock (migrating legacy 18-col headers if present)
    with csv_logger._lock:
        _ensure_csv_header(summary_path, TEST_SUMMARY_COLUMNS)
        with open(summary_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TEST_SUMMARY_COLUMNS)
            writer.writerow(summary_row)

    return summary_row
