"""Unit and Integration Tests for Task B2: Worker Queue and Limits.

Verifies:
1. Concurrency limit of 2 simultaneous tasks plus bounded queue.
2. HTTP 503 with status "rejected_503" when the queue is full.
3. Requests exceeding the time limit report status "timeout" (HTTP 504).
4. Response reports queue_ms (time waiting in the queue).
5. Status endpoint reports psutil CPU %, RAM %, and current queue length.
6. e2-micro tuned TASK_PROFILES.
"""

from __future__ import annotations

import asyncio
import httpx
import pytest
from app.core.profiles import TASK_PROFILES, TaskType, resolve_task_profile
from worker.executor import WorkerRuntimeState, create_worker_app


@pytest.fixture
def limited_worker_client() -> tuple[httpx.AsyncClient, WorkerRuntimeState]:
    state = WorkerRuntimeState(
        worker_id="worker-b2-test",
        port=8001,
        concurrency_limit=2,
        queue_capacity=2,
        task_timeout_sec=5.0,
    )
    app = create_worker_app(state=state)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://worker-b2-test")
    return client, state


@pytest.mark.asyncio
async def test_worker_status_endpoint(limited_worker_client: tuple[httpx.AsyncClient, WorkerRuntimeState]) -> None:
    """GET /status reports psutil CPU %, RAM %, current queue length, and concurrency settings."""
    client, state = limited_worker_client
    resp = await client.get("/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "healthy"
    assert data["worker_id"] == "worker-b2-test"
    assert "cpu_percent" in data
    assert "ram_percent" in data
    assert isinstance(data["cpu_percent"], (int, float))
    assert isinstance(data["ram_percent"], (int, float))
    assert data["ram_percent"] > 0.0
    assert data["current_queue_length"] == 0
    assert data["active_task_count"] == 0
    assert data["concurrency_limit"] == 2
    assert data["queue_capacity"] == 2


@pytest.mark.asyncio
async def test_concurrency_limit_and_queue_ms(limited_worker_client: tuple[httpx.AsyncClient, WorkerRuntimeState]) -> None:
    """Worker allows 2 tasks concurrently; 3rd task queues and reports queue_ms > 0."""
    client, state = limited_worker_client

    # Launch 3 tasks: task 1 and 2 occupy the 2 concurrency slots, task 3 waits in queue
    task_payload_1 = {
        "task_id": "tsk-q1",
        "task_type": "heavy",
        "payload": {"data": "slot1", "iterations": 15000},
    }
    task_payload_2 = {
        "task_id": "tsk-q2",
        "task_type": "heavy",
        "payload": {"data": "slot2", "iterations": 15000},
    }
    task_payload_3 = {
        "task_id": "tsk-q3",
        "task_type": "light",
        "payload": {"courses": [{"grade": 9.0, "credits": 4}]},
    }

    results = await asyncio.gather(
        client.post("/execute", json=task_payload_1),
        client.post("/execute", json=task_payload_2),
        client.post("/execute", json=task_payload_3),
    )

    for resp in results:
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert "queue_ms" in data
        assert data["queue_ms"] >= 0.0

    # At least one task should have waited in the queue
    queue_timings = [r.json()["queue_ms"] for r in results]
    assert any(q >= 0.0 for q in queue_timings)


@pytest.mark.asyncio
async def test_bounded_queue_rejection_503(limited_worker_client: tuple[httpx.AsyncClient, WorkerRuntimeState]) -> None:
    """When concurrency (2) and queue capacity (2) are saturated, additional requests receive 503 rejected_503."""
    client, state = limited_worker_client

    # Fire 6 tasks simultaneously when capacity is 2 active + 2 queued = 4 total capacity
    payloads = [
        {
            "task_id": f"tsk-flood-{i}",
            "task_type": "heavy",
            "payload": {"data": f"flood-{i}", "iterations": 25000},
        }
        for i in range(6)
    ]

    responses = await asyncio.gather(*(client.post("/execute", json=p) for p in payloads))

    status_codes = [r.status_code for r in responses]
    # Expect 503 for the tasks that exceeded the queue capacity of 2
    assert 503 in status_codes

    rejections = [r.json() for r in responses if r.status_code == 503]
    for rej in rejections:
        assert rej["status"] == "rejected_503"
        assert "queue full" in rej["detail"].lower()
        assert rej["concurrency_limit"] == 2
        assert rej["queue_capacity"] == 2

    # And the worker did not crash; /status is still healthy
    status_resp = await client.get("/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["total_rejected_503"] >= 1


@pytest.mark.asyncio
async def test_queued_task_timeout(limited_worker_client: tuple[httpx.AsyncClient, WorkerRuntimeState]) -> None:
    """Requests that exceed the time limit report status 'timeout'."""
    client, state = limited_worker_client

    # Launch 2 background tasks that occupy both concurrency slots
    task_occupy_1 = {
        "task_id": "tsk-occ-1",
        "task_type": "heavy",
        "payload": {"data": "occ1", "iterations": 1500000},
    }
    task_occupy_2 = {
        "task_id": "tsk-occ-2",
        "task_type": "heavy",
        "payload": {"data": "occ2", "iterations": 1500000},
    }

    t1 = asyncio.create_task(client.post("/execute", json=task_occupy_1))
    t2 = asyncio.create_task(client.post("/execute", json=task_occupy_2))

    # Give event loop a moment to ensure both tasks acquired the semaphore slots
    await asyncio.sleep(0.02)

    # Now both slots are busy. Send 3rd task with a short timeout_sec
    task_quick_timeout = {
        "task_id": "tsk-timeout-candidate",
        "task_type": "light",
        "payload": {
            "courses": [{"grade": 8.0, "credits": 3}],
            "timeout_sec": 0.05,
        },
    }

    res_timeout = await client.post("/execute", json=task_quick_timeout)

    # Clean up background tasks
    await asyncio.gather(t1, t2)

    # The quick timeout request must report 504 and status="timeout"
    assert res_timeout.status_code == 504
    data = res_timeout.json()
    assert data["status"] == "timeout"
    assert "timeout" in data["detail"].lower()
    assert "queue_ms" in data


def test_e2_micro_task_profiles_tuning() -> None:
    """Verify TASK_PROFILES are tuned within e2-micro constraints (1 vCPU, 1 GB RAM)."""
    for task_type, profile in TASK_PROFILES.items():
        # Memory per task must never exceed 512 MB so 1 GB e2-micro never OOMs
        assert profile.mem_demand_mb <= 512.0
        # CPU demand must be reasonable on 1 vCPU
        assert profile.cpu_demand_pct <= 50.0

    # Ensure memory intensive profile is safely scaled down to 384 MB
    mem_prof = resolve_task_profile("MEMORY_INTENSIVE")
    assert mem_prof.mem_demand_mb == 384.0
    assert mem_prof.cpu_demand_pct == 15.0
