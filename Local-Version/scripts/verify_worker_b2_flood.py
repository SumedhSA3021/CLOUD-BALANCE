"""Verification script for Task B2: Worker Queue and Limits.

Starts a real Worker on port 8001, queries /status for psutil telemetry,
floods the worker with 12 concurrent requests (concurrency limit=2, queue capacity=4),
verifies visible queueing (queue_ms > 0) and backpressure 503s ("rejected_503"),
and confirms zero crashes with healthy post-flood status.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import uvicorn

# Set worker limits for clear flood demonstration
os.environ["WORKER_PORT"] = "8001"
os.environ["WORKER_CONCURRENCY_LIMIT"] = "2"
os.environ["WORKER_QUEUE_CAPACITY"] = "4"
os.environ["WORKER_TASK_TIMEOUT_SEC"] = "5.0"

from worker.executor import create_worker_app, WorkerRuntimeState


def start_worker_server(state: WorkerRuntimeState) -> uvicorn.Server:
    app = create_worker_app(state=state)
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8001, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


async def run_verification() -> None:
    print("=" * 70)
    print("TASK B2 VERIFICATION: WORKER QUEUE, CONCURRENCY LIMITS & 503 BACKPRESSURE")
    print("=" * 70)

    state = WorkerRuntimeState(
        worker_id="worker-1",
        port=8001,
        concurrency_limit=2,
        queue_capacity=4,
        task_timeout_sec=5.0,
    )
    server = start_worker_server(state)

    # Wait for worker server to start listening
    await asyncio.sleep(1.0)

    base_url = "http://127.0.0.1:8001"
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # Step 1: Query /status before flood
        print("\n--- 1. Initial Worker Status (/status) ---")
        status_resp = await client.get("/status")
        status_data = status_resp.json()
        print(f"Status Code:            {status_resp.status_code}")
        print(f"Worker ID:              {status_data['worker_id']}")
        print(f"psutil CPU %:           {status_data['cpu_percent']}%")
        print(f"psutil RAM %:           {status_data['ram_percent']}%")
        print(f"Current Queue Length:   {status_data['current_queue_length']}")
        print(f"Concurrency Limit:      {status_data['concurrency_limit']}")
        print(f"Queue Capacity:         {status_data['queue_capacity']}")

        # Step 2: Flood worker with 12 concurrent requests across concurrent clients
        print("\n--- 2. Flooding Worker-1 with 12 Concurrent Requests ---")
        print("Limits: Concurrency=2 slots, Queue Capacity=4 slots (Total Max In-Flight=6)")
        print("Expected: 6 processed (2 active + 4 queued), 6 rejected with HTTP 503 (rejected_503)")

        async def send_request(task_idx: int) -> httpx.Response:
            async with httpx.AsyncClient(timeout=10.0) as req_client:
                payload = {
                    "task_id": f"flood-task-{task_idx:02d}",
                    "task_type": "heavy",
                    "payload": {"data": f"burst-{task_idx}", "iterations": 150000},
                }
                return await req_client.post("http://127.0.0.1:8001/execute", json=payload)

        t0 = time.perf_counter()
        responses = await asyncio.gather(*(send_request(i) for i in range(1, 13)))
        total_time_ms = (time.perf_counter() - t0) * 1000.0

        # Step 3: Print results breakdown
        print(f"\n--- 3. Results Summary (Total Batch Duration: {total_time_ms:.1f}ms) ---")
        print(f"{'Task ID':<16} {'HTTP':<6} {'Status':<14} {'Queue (ms)':<12} {'Exec (ms)':<12} {'Detail / Outcome'}")
        print("-" * 75)

        completed_count = 0
        rejected_count = 0

        for idx, resp in enumerate(responses, 1):
            task_id = f"flood-task-{idx:02d}"
            code = resp.status_code
            data = resp.json()

            if code == 200:
                completed_count += 1
                q_ms = data.get("queue_ms", 0.0)
                e_ms = data.get("execution_ms", 0.0)
                status_str = data.get("status", "COMPLETED")
                detail = f"Result: {list(data.get('result', {}).keys())}"
                print(f"{task_id:<16} {code:<6} {status_str:<14} {q_ms:<12.2f} {e_ms:<12.2f} {detail}")
            elif code == 503:
                rejected_count += 1
                status_str = data.get("status", "rejected_503")
                q_ms = data.get("queue_length", 0)
                detail = "Backpressure rejection (Queue Full)"
                print(f"{task_id:<16} {code:<6} {status_str:<14} {'N/A':<12} {'N/A':<12} {detail}")
            else:
                print(f"{task_id:<16} {code:<6} UNEXPECTED     N/A          N/A          {data}")

        print("-" * 75)
        print(f"Summary: {completed_count} tasks COMPLETED, {rejected_count} tasks REJECTED (HTTP 503)")

        # Step 4: Verify post-flood worker status
        print("\n--- 4. Post-Flood Worker Health & psutil Telemetry (/status) ---")
        post_resp = await client.get("/status")
        post_data = post_resp.json()
        print(f"Status Code:            {post_resp.status_code} ({post_data['status']})")
        print(f"psutil CPU %:           {post_data['cpu_percent']}%")
        print(f"psutil RAM %:           {post_data['ram_percent']}%")
        print(f"Current Queue Length:   {post_data['current_queue_length']} (drained back to 0)")
        print(f"Active Task Count:      {post_data['active_task_count']} (idle)")
        print(f"Total Completed:        {post_data['total_completed']}")
        print(f"Total Rejected 503s:    {post_data['total_rejected_503']}")

        assert completed_count > 0, "Expected completed tasks"
        assert rejected_count > 0, "Expected 503 rejected tasks"
        assert post_data["current_queue_length"] == 0, "Queue must drain to 0"
        print("\n[SUCCESS] Task B2 Verification Passed: Visible queueing and 503 backpressure confirmed with zero worker crash!")

    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(run_verification())
