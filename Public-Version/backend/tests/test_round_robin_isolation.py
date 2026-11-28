"""Unit and Integration Tests for Task A1: Round Robin Isolation Fix.

Verifies:
1. Redis atomic INCR counter operation (rr_counter).
2. Strict isolation of Round Robin from OR-Tools MILP solver (solver_call_count == 0).
3. Micro-batch buffer bypass in Round Robin mode.
4. Strict worker-1 -> worker-2 -> worker-3 cyclic sequence under concurrent clients.
5. Recording of scheduler_used and dispatch_seq on tasks and assignments.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from app.schedulers.ortools_milp import get_solver_call_count, reset_solver_call_count


@pytest.mark.asyncio
async def test_redis_incr_atomic() -> None:
    """Verify DualRedisClient / InMemoryTTLStore incr method increments atomically."""
    from app.core.redis_client import DualRedisClient

    client = DualRedisClient(force_memory=True)
    await client.connect()

    v1 = await client.incr("rr_counter")
    v2 = await client.incr("rr_counter")
    v3 = await client.incr("rr_counter")

    assert v1 == 1
    assert v2 == 2
    assert v3 == 3
    await client.close()


@pytest.mark.asyncio
async def test_round_robin_isolation_and_zero_solver_calls() -> None:
    """In round_robin mode, tasks bypass batcher buffer and MILP solver call count is 0."""
    reset_solver_call_count()
    assert get_solver_call_count() == 0

    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        default_scheduler="round_robin",
    )
    app = create_app(settings=cfg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        worker_headers = {"X-Worker-Secret": cfg.worker_secret}
        admin_headers = {"Authorization": f"Bearer {cfg.admin_token}"}
        # Seed 3 virtual workers
        for wid, port in (("worker-1", 8001), ("worker-2", 8002), ("worker-3", 8003)):
            await client.post(
                "/api/v1/telemetry",
                headers=worker_headers,
                json={
                    "worker_id": wid,
                    "ip_address": "virtual",
                    "port": port,
                    "cpu_percent": 15.0,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 512.0,
                    "memory_percent": 12.5,
                    "load_avg_1m": 0.5,
                    "active_task_count": 0,
                },
            )

        # Switch to round_robin mode explicitly to be 100% sure
        await client.post("/api/v1/control/scheduler", headers=admin_headers, json={"scheduler": "round_robin"})

        # Submit 3 tasks sequentially via unified POST /tasks pipeline
        responses = []
        for i in range(3):
            resp = await client.post(
                "/tasks",
                json={"client_id": f"laptop-{i}", "task_type": "light"},
            )
            assert resp.status_code == 200
            responses.append(resp.json())

        # Verify queue depth stays 0 and solver_call_count is strictly 0 in RR mode
        assert app.state.scheduler_state.queue_depth == 0
        assert get_solver_call_count() == 0

        # Verify assigned workers cycle strictly w1, w2, w3
        assert responses[0]["assigned_worker"] == "worker-1"
        assert responses[0]["dispatch_seq"] == 1
        assert responses[0]["scheduler_used"] == "round_robin"

        assert responses[1]["assigned_worker"] == "worker-2"
        assert responses[1]["dispatch_seq"] == 2
        assert responses[1]["scheduler_used"] == "round_robin"

        assert responses[2]["assigned_worker"] == "worker-3"
        assert responses[2]["dispatch_seq"] == 3
        assert responses[2]["scheduler_used"] == "round_robin"


@pytest.mark.asyncio
async def test_30_concurrent_round_robin_requests_strict_cycle() -> None:
    """Fire 30 concurrent requests under round_robin, verify strict w1, w2, w3 pattern sorted by dispatch_seq."""
    reset_solver_call_count()

    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        default_scheduler="round_robin",
    )
    app = create_app(settings=cfg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Seed 3 virtual workers
        for wid, port in (("worker-1", 8001), ("worker-2", 8002), ("worker-3", 8003)):
            await client.post(
                "/api/v1/telemetry",
                headers={"X-Worker-Secret": cfg.worker_secret},
                json={
                    "worker_id": wid,
                    "ip_address": "virtual",
                    "port": port,
                    "cpu_percent": 15.0,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 512.0,
                    "memory_percent": 12.5,
                    "load_avg_1m": 0.5,
                    "active_task_count": 0,
                },
            )

        # Reset rr_counter to start cleanly from 1
        await app.state.redis_client.delete("rr_counter")

        # Fire 30 concurrent requests from 3 concurrent clients (>= 10 each)
        async def submit_client_batch(client_idx: int) -> list[dict]:
            batch = []
            for _j in range(10):
                r = await client.post(
                    "/tasks",
                    json={
                        "client_id": f"laptop-{client_idx}",
                        "task_type": "light",
                    },
                )
                assert r.status_code == 200
                batch.append(r.json())
            return batch

        grouped = await asyncio.gather(*[submit_client_batch(c) for c in (1, 2, 3)])
        results = [row for sub in grouped for row in sub]

        # Sort results by dispatch_seq
        sorted_results = sorted(results, key=lambda r: r["dispatch_seq"])

        # Check all 30 sequence numbers are 1..30
        seqs = [r["dispatch_seq"] for r in sorted_results]
        assert seqs == list(range(1, 31))

        # Check strict w1, w2, w3 cycle
        expected_workers = ["worker-1", "worker-2", "worker-3"] * 10
        actual_workers = [r["assigned_worker"] for r in sorted_results]
        assert actual_workers == expected_workers

        # Check solver call count is strictly 0
        assert get_solver_call_count() == 0

        # Check history recorded scheduler_used and dispatch_seq
        recent = app.state.history.get_recent_assignments(limit=30)
        assert len(recent) == 30
        for item in recent:
            assert item.scheduler == "round_robin"
            assert item.scheduler_used == "round_robin"
            assert item.dispatch_seq is not None


@pytest.mark.asyncio
async def test_milp_mode_still_calls_solver() -> None:
    """Verify that when mode is milp, solver is invoked and solver_call_count increments."""
    reset_solver_call_count()
    assert get_solver_call_count() == 0

    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        default_scheduler="ortools_milp",
    )
    app = create_app(settings=cfg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Seed 3 virtual workers
        for wid, port in (("worker-1", 8001), ("worker-2", 8002), ("worker-3", 8003)):
            await client.post(
                "/api/v1/telemetry",
                headers={"X-Worker-Secret": cfg.worker_secret},
                json={
                    "worker_id": wid,
                    "ip_address": "virtual",
                    "port": port,
                    "cpu_percent": 15.0,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 512.0,
                    "memory_percent": 12.5,
                    "load_avg_1m": 0.5,
                    "active_task_count": 0,
                },
            )

        # Submit task in milp mode via unified POST /tasks
        r = await client.post(
            "/tasks",
            json={"client_id": "laptop-milp", "task_type": "heavy", "size": 5000},
        )
        assert r.status_code == 200
        assert r.json()["scheduler_used"] == "ortools_milp"

        # Solver was called directly inline!
        assert get_solver_call_count() == 1
