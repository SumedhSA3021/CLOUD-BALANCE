"""Distributed Load Generator Client for CloudBalance Benchmark Runs (Task D1).

Usage:
    python tools/load_client.py --url http://localhost:8000 --laptop 1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

import httpx
import numpy as np


async def wait_for_armed_state(
    client: httpx.AsyncClient,
    url: str,
    laptop_no: int,
    poll_interval: float = 0.5,
) -> dict[str, Any]:
    """Poll /test/status until state == 'armed'."""
    print(f"[laptop-{laptop_no}] Polling {url}/test/status for active test...")
    last_state = None
    while True:
        try:
            resp = await client.get(f"{url}/test/status", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("state", "idle")
                if state != last_state:
                    print(f"[laptop-{laptop_no}] Current test state: {state}")
                    last_state = state
                if state == "armed":
                    return data
        except Exception as e:
            print(f"[laptop-{laptop_no}] Polling note: {e}")
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
    except Exception:
        counter["failed"] += 1


async def run_load_client(url: str, laptop_no: int) -> None:
    client_id = f"laptop-{laptop_no}"
    clean_url = url.rstrip("/")

    async with httpx.AsyncClient() as client:
        # 1. Poll /test/status until state == "armed"
        test_info = await wait_for_armed_state(client, clean_url, laptop_no)

        mode = str(test_info.get("mode", "round_robin"))
        duration_s = float(test_info.get("duration_s", 30.0))
        lambda_rate = float(test_info.get("lambda_per_client", 5.0))
        heavy_ratio = float(test_info.get("heavy_ratio", 0.2))
        seed = int(test_info.get("seed", 42))
        start_at = float(test_info.get("start_at", time.time()))

        print(
            f"[{client_id}] Test Armed: mode={mode}, duration={duration_s}s, "
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
        print(f"[{client_id}] Generated {len(schedule)} scheduled tasks for {duration_s}s duration.")

        # 3. Sleep until start_at
        now = time.time()
        delay_to_start = start_at - now
        if delay_to_start > 0:
            print(f"[{client_id}] Sleeping {delay_to_start:.2f}s until start_at ({start_at})...")
            await asyncio.sleep(delay_to_start)

        # 4. Send tasks asynchronously without waiting for replies, stop at duration_s
        start_wall = time.time()
        counter = {"ok": 0, "failed": 0}
        in_flight_tasks: list[asyncio.Task[None]] = []

        print(f"[{client_id}] Beginning workload dispatch...")
        for offset, task_type in schedule:
            elapsed = time.time() - start_wall
            if elapsed >= duration_s:
                break

            target_wall = start_wall + offset
            wait_gap = target_wall - time.time()
            if wait_gap > 0:
                await asyncio.sleep(wait_gap)

            if time.time() - start_wall >= duration_s:
                break

            # Launch asynchronous task
            t = asyncio.create_task(
                send_single_task(client, clean_url, client_id, task_type, counter)
            )
            in_flight_tasks.append(t)

        sent_count = len(in_flight_tasks)

        # Wait for pending responses up to 15s draining limit
        if in_flight_tasks:
            await asyncio.wait(in_flight_tasks, timeout=15.0)

        # 5. Print sent / ok / failed at the end
        print(f"sent: {sent_count} | ok: {counter['ok']} | failed: {counter['failed']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudBalance Benchmark Load Client")
    parser.add_argument("--url", default="http://localhost:8000", help="Controller base URL")
    parser.add_argument("--laptop", type=int, default=1, help="Laptop client number (e.g. 1, 2, 3)")
    args = parser.parse_args()

    asyncio.run(run_load_client(args.url, args.laptop))


if __name__ == "__main__":
    main()
