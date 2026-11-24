"""Unit and Integration Tests for Task B1: Worker Task Functions.

Verifies:
1. task_type 'light': CGPA weighted average calculation and input validation.
2. task_type 'heavy': SHA-256 iterative hashing loop with configurable iterations.
3. Payload size rejection (413 Payload Too Large / 400 Bad Request).
4. Worker returns result plus measured execution_ms.
"""

from __future__ import annotations

import pytest
import httpx
from worker.executor import create_worker_app, WorkerRuntimeState


@pytest.fixture
def worker_client() -> httpx.AsyncClient:
    state = WorkerRuntimeState(worker_id="worker-test", port=8001)
    app = create_worker_app(state=state)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://worker-test")


@pytest.mark.asyncio
async def test_light_task_cgpa_calculation_with_courses(worker_client: httpx.AsyncClient) -> None:
    """task_type 'light' accurately calculates weighted CGPA from course items."""
    payload = {
        "task_id": "tsk-light-1",
        "task_type": "light",
        "payload": {
            "courses": [
                {"name": "Data Structures", "credits": 4, "grade": 9.0},
                {"name": "Operating Systems", "credits": 4, "grade": 8.5},
                {"name": "Computer Networks", "credits": 3, "grade": 9.0},
            ]
        },
    }
    resp = await worker_client.post("/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "COMPLETED"
    assert data["task_type"] == "light"
    assert data["worker_id"] == "worker-test"
    assert "execution_ms" in data
    assert data["execution_ms"] >= 0.0

    result = data["result"]
    # (4 * 9.0 + 4 * 8.5 + 3 * 9.0) / 11 = 97 / 11 = 8.8181... -> 8.82
    assert result["cgpa"] == 8.82
    assert result["total_credits"] == 11.0
    assert result["course_count"] == 3


@pytest.mark.asyncio
async def test_light_task_cgpa_with_grades_array(worker_client: httpx.AsyncClient) -> None:
    """task_type 'light' accurately calculates CGPA with grades and credits arrays."""
    payload = {
        "task_id": "tsk-light-2",
        "task_type": "light",
        "payload": {
            "grades": [8.0, 9.0, 10.0],
            "credits": [3, 4, 3],
        },
    }
    resp = await worker_client.post("/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    result = data["result"]
    # (3*8 + 4*9 + 3*10) / 10 = (24 + 36 + 30) / 10 = 90 / 10 = 9.0
    assert result["cgpa"] == 9.0
    assert result["total_credits"] == 10.0
    assert result["course_count"] == 3


@pytest.mark.asyncio
async def test_light_task_invalid_inputs_rejected(worker_client: httpx.AsyncClient) -> None:
    """task_type 'light' returns 400 for empty or out-of-range inputs."""
    # Empty payload
    r1 = await worker_client.post(
        "/execute",
        json={"task_id": "t1", "task_type": "light", "payload": {}},
    )
    assert r1.status_code == 400
    assert "courses" in r1.json()["detail"] or "grades" in r1.json()["detail"]

    # Grade > 10.0
    r2 = await worker_client.post(
        "/execute",
        json={
            "task_id": "t2",
            "task_type": "light",
            "payload": {"courses": [{"name": "Math", "credits": 4, "grade": 12.0}]},
        },
    )
    assert r2.status_code == 400
    assert "between 0.0 and 10.0" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_heavy_task_hashing_loop(worker_client: httpx.AsyncClient) -> None:
    """task_type 'heavy' performs SHA-256 hashing loop and returns execution timing."""
    iterations = 20000
    payload = {
        "task_id": "tsk-heavy-1",
        "task_type": "heavy",
        "payload": {
            "data": "test-data-payload-hash-seed",
            "iterations": iterations,
        },
    }
    resp = await worker_client.post("/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "COMPLETED"
    assert data["task_type"] == "heavy"
    assert "execution_ms" in data
    assert data["execution_ms"] > 0.0

    result = data["result"]
    assert result["algorithm"] == "sha256"
    assert result["iterations"] == iterations
    assert len(result["final_hash"]) == 64


@pytest.mark.asyncio
async def test_payload_size_limit_rejection(worker_client: httpx.AsyncClient) -> None:
    """Payload sizes exceeding safe limit are rejected with 413 Payload Too Large."""
    huge_data = "X" * (70 * 1024)  # 70 KB exceeds 64 KB limit
    payload = {
        "task_id": "tsk-large",
        "task_type": "light",
        "payload": {"data": huge_data},
    }
    resp = await worker_client.post("/execute", json=payload)
    assert resp.status_code == 413
    assert "exceeds maximum safe limit" in resp.json()["detail"]
