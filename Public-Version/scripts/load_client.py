"""Distributed Load Generator Client for CloudBalance Benchmark Runs (Task D1).

Usage:
    python scripts/load_client.py --controller http://127.0.0.1:8000 --client-id client-1 --laptop-no 1
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np


def _resolve_default_controller_url() -> str:
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if backend_dir.is_dir() and str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    try:
        from app.core.config import ClientSettings

        return ClientSettings().controller_url
    except ImportError:
        return (
            os.getenv("CB_BASE_URL")
            or os.getenv("CONTROLLER_URL")
            or os.getenv("CB_CONTROLLER_URL")
            or "http://127.0.0.1:8000"
        )


async def wait_for_armed_state(
    client: httpx.AsyncClient,
    url: str,
    client_id: str,
    poll_interval: float = 0.5,
) -> dict[str, Any]:
    """Poll /test/status until state == 'armed'."""
    print(f"[{client_id}] Polling {url}/test/status for active test...")
    last_state = None
    while True:
        try:
            resp = await client.get(f"{url}/test/status", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("state", "idle")
                if state != last_state:
                    print(f"[{client_id}] Current test state: {state}")
                    last_state = state
                if state == "armed":
                    return data
        except (httpx.HTTPError, OSError, TimeoutError, ValueError) as e:
            print(f"[{client_id}] Polling note: {e}")
        await asyncio.sleep(poll_interval)


def build_deterministic_schedule(
    duration_s: float,
    lambda_rate: float,
    heavy_ratio: float,
    seed: int,
    laptop_no: int,
) -> list[tuple[float, str]]:
    """Build the full schedule BEFORE starting, deterministically from seed + laptop_no.

    Exponential inter-arrival times with mean 1 / lambda_rate.
    Heavy task with probability heavy_ratio.
    """
    rng = np.random.default_rng(seed + laptop_no)
    schedule: list[tuple[float, str]] = []
    curr_time = 0.0
    mean_gap = 1.0 / max(0.001, lambda_rate)

    while curr_time < duration_s:
        gap = float(rng.exponential(scale=mean_gap))
        curr_time += gap
        if curr_time >= duration_s:
            break
        is_heavy = float(rng.random()) < heavy_ratio
        task_type = "heavy" if is_heavy else "light"
        schedule.append((curr_time, task_type))

    return schedule


async def send_single_task(
    client: httpx.AsyncClient,
    url: str,
    client_id: str,
    task_type: str,
    counter: dict[str, int],
) -> None:
    """Send one task asynchronously to POST /tasks."""
    sent_at = time.time()
    payload = {
        "client_id": client_id,
        "task_type": task_type,
        "sent_at": sent_at,
        "size": 150000 if task_type == "heavy" else 4,
    }
    try:
        resp = await client.post(f"{url}/tasks", json=payload, timeout=20.0)
        if resp.status_code == 200:
            counter["ok"] += 1
        else:
            counter["failed"] += 1
    except (httpx.HTTPError, OSError, TimeoutError, ValueError):
        counter["failed"] += 1


async def _watch_test_status(
    client: httpx.AsyncClient,
    url: str,
    test_id: str | None,
    stop_event: asyncio.Event,
) -> None:
    """Stop dispatching early if controller test state leaves running/armed."""
    while not stop_event.is_set():
        await asyncio.sleep(0.5)
        try:
            resp = await client.get(f"{url}/test/status", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                st = str(data.get("state", "idle")).lower()
                cur_id = data.get("test_id")
                if st not in ("armed", "running") or (test_id and cur_id != test_id):
                    stop_event.set()
                    return
        except (httpx.HTTPError, OSError, TimeoutError, ValueError):
            pass


async def run_load_client(
    url: str,
    laptop_no: int,
    client_id: str | None = None,
) -> tuple[int, int, int]:
    resolved_client_id = (client_id or "").strip() or f"laptop-{laptop_no}"
    clean_url = url.rstrip("/")

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(limits=limits) as client:
        # 1. Poll /test/status until state == "armed"
        test_info = await wait_for_armed_state(client, clean_url, resolved_client_id)

        test_id = test_info.get("test_id")
        mode = str(test_info.get("mode", "round_robin"))
        duration_s = float(test_info.get("duration_s", 60.0))
        lambda_rate = float(test_info.get("lambda_per_client", 3.0))
        heavy_ratio = float(test_info.get("heavy_ratio", 0.3))
        seed = int(test_info.get("seed", 42))
        start_at = float(test_info.get("start_at", time.time()))

        print(
            f"[{resolved_client_id}] Test Armed: test_id={test_id}, mode={mode}, duration={duration_s}s, "
            f"lambda={lambda_rate}, heavy_ratio={heavy_ratio}, seed={seed}, start_at={start_at}"
        )

        # 2. Build full schedule BEFORE starting, deterministically from seed + laptop_no
        schedule = build_deterministic_schedule(
            duration_s=duration_s,
            lambda_rate=lambda_rate,
            heavy_ratio=heavy_ratio,
            seed=seed,
            laptop_no=laptop_no,
        )
        print(
            f"[{resolved_client_id}] Generated {len(schedule)} scheduled tasks "
            f"(seed={seed + laptop_no}) for {duration_s}s."
        )

        # 3. Sleep until start_at
        now = time.time()
        delay_to_start = start_at - now
        if delay_to_start > 0:
            print(f"[{resolved_client_id}] Sleeping {delay_to_start:.2f}s until start_at ({start_at})...")
            await asyncio.sleep(delay_to_start)

        # 4. Send tasks asynchronously without waiting for replies; stop at duration_s or test end
        start_mono = time.monotonic()
        counter = {"ok": 0, "failed": 0}
        in_flight_tasks: list[asyncio.Task[None]] = []
        stop_event = asyncio.Event()
        watcher = asyncio.create_task(
            _watch_test_status(client, clean_url, test_id, stop_event)
        )

        print(f"[{resolved_client_id}] Beginning workload dispatch...")
        try:
            for offset, task_type in schedule:
                if stop_event.is_set() or (time.monotonic() - start_mono) >= duration_s:
                    break

                target_mono = start_mono + offset
                wait_gap = target_mono - time.monotonic()
                if wait_gap > 0:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=wait_gap)
                        break
                    except TimeoutError:
                        pass

                if stop_event.is_set() or (time.monotonic() - start_mono) >= duration_s:
                    break

                t = asyncio.create_task(
                    send_single_task(client, clean_url, resolved_client_id, task_type, counter)
                )
                in_flight_tasks.append(t)
        finally:
            stop_event.set()
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

        sent_count = len(in_flight_tasks)

        # Wait for pending responses up to 15s draining limit
        if in_flight_tasks:
            _done, pending = await asyncio.wait(in_flight_tasks, timeout=15.0)
            for p_task in pending:
                p_task.cancel()
                counter["failed"] += 1

        # 5. Print sent / ok / failed at the end
        print(f"sent: {sent_count} | ok: {counter['ok']} | failed: {counter['failed']}")
        return sent_count, counter["ok"], counter["failed"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_base_url = _resolve_default_controller_url()
    parser = argparse.ArgumentParser(description="CloudBalance Benchmark Load Client")
    parser.add_argument(
        "--controller",
        "--url",
        dest="controller",
        default=default_base_url,
        help="Controller base URL (default: Settings.controller_url / env CB_BASE_URL)",
    )
    parser.add_argument(
        "--laptop-no",
        "--laptop",
        dest="laptop_no",
        type=int,
        default=1,
        help="Client stream index used for deterministic seed (seed + laptop_no)",
    )
    parser.add_argument(
        "--client-id",
        dest="client_id",
        default=None,
        help="Client identifier label (e.g. client-1; defaults to laptop-<laptop-no> if omitted)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_load_client(args.controller, args.laptop_no, args.client_id))


if __name__ == "__main__":
    main()
