"""End-to-End Integration Tests for Phase 3: Controller Services, Failover, Backpressure, and WebSocket."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_controller_task_flow_telemetry_and_scheduler_hotswap() -> None:
    """Verify telemetry ingestion, task submission, micro-batch flush, and scheduler hot-swap."""
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        max_queue_depth=10,
        batch_window_ms=50,
        batch_max_size=5,
    )
    app = create_app(settings=cfg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://controller") as client:
        # 1. Health & Ready probes
        h_resp = await client.get("/health")
        assert h_resp.status_code == 200
        assert h_resp.headers.get("X-Correlation-ID")

        r_resp = await client.get("/ready")
        assert r_resp.status_code == 200
        assert r_resp.json()["ready"] is True

        # 2. Post telemetry for 2 virtual workers
        for wid, cpu in (("worker-1", 15.0), ("worker-2", 40.0)):
            t_resp = await client.post(
                "/api/v1/telemetry",
                json={
                    "worker_id": wid,
                    "ip_address": "virtual",
                    "port": 8001,
                    "cpu_percent": cpu,
                    "memory_total_mb": 4096.0,
                    "memory_used_mb": 1024.0,
                    "memory_percent": 25.0,
                    "load_avg_1m": 0.5,
                    "active_task_count": 0,
                },
            )
            assert t_resp.status_code == 200
            assert t_resp.json()["accepted"] is True

        w_resp = await client.get("/api/v1/telemetry/workers")
        assert len(w_resp.json()) == 2

        # 3. Submit 3 tasks from different client laptops
        for cid, ttype in (
            ("laptop-a", "CPU_INTENSIVE"),
            ("laptop-b", "MEMORY_INTENSIVE"),
            ("laptop-c", "LIGHTWEIGHT_QUERY"),
        ):
            sub_resp = await client.post(
                "/api/v1/tasks",
                json={"client_id": cid, "task_type": ttype},
            )
            assert sub_resp.status_code == 202
            assert sub_resp.json()["client_id"] == cid

        # Flush micro-batch and wait for dispatch completion
        assignments = await app.state.batcher.flush_one_batch(wait_for_dispatch=True)
        assert len(assignments) == 3

        recent_resp = await client.get("/api/v1/tasks/recent?limit=10")
        assert recent_resp.status_code == 200
        recent_data = recent_resp.json()
        assert len(recent_data) == 3
        assert all(item["status"] == "COMPLETED" for item in recent_data)

        # Filtered recent tasks by client_id
        laptop_a_resp = await client.get("/api/v1/tasks/recent?client_id=laptop-a")
        assert len(laptop_a_resp.json()) == 1
        assert laptop_a_resp.json()[0]["client_id"] == "laptop-a"

        # 4. Hot-swap scheduler to round_robin and least_connections
        swap_resp = await client.post(
            "/api/v1/control/scheduler",
            json={"scheduler": "round_robin"},
        )
        assert swap_resp.status_code == 200
        assert swap_resp.json()["active_scheduler"] == "round_robin"

        # 5. Traffic control: inject spike and toggle pause
        traf_resp = await client.post(
            "/api/v1/control/traffic",
            json={
                "lambda_rate": 24.0,
                "paused": False,
                "spike_tasks": 3,
                "spike_client_id": "laptop-spike",
                "spike_task_type": "BALANCED_COMPUTE",
            },
        )
        assert traf_resp.status_code == 200
        assert traf_resp.json()["injected_spike_tasks"] == 3
        await app.state.batcher.flush_one_batch(wait_for_dispatch=True)

        # 6. Verify profiles endpoint and snapshot endpoint
        prof_resp = await client.get("/api/v1/tasks/profiles")
        assert prof_resp.status_code == 200
        assert "CPU_INTENSIVE" in prof_resp.json()

        snap_resp = await client.get("/api/v1/control/snapshot")
        assert snap_resp.status_code == 200
        snap = snap_resp.json()
        assert snap["type"] == "CLUSTER_SNAPSHOT"
        assert len(snap["workers"]) == 2
        assert len(snap["clients"]) >= 3


@pytest.mark.asyncio
async def test_backpressure_429_when_queue_full() -> None:
    """Verify HTTP 429 Too Many Requests is returned when queue depth reaches max_queue_depth."""
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        max_queue_depth=2,
        rate_limit_per_sec=100,
    )
    app = create_app(settings=cfg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://controller") as client:
        r1 = await client.post(
            "/api/v1/tasks",
            json={"client_id": "laptop-1", "task_type": "LIGHTWEIGHT_QUERY"},
        )
        assert r1.status_code == 202

        r2 = await client.post(
            "/api/v1/tasks",
            json={"client_id": "laptop-1", "task_type": "LIGHTWEIGHT_QUERY"},
        )
        assert r2.status_code == 202

        # 3rd task exceeds max_queue_depth=2 -> must return 429
        r3 = await client.post(
            "/api/v1/tasks",
            json={"client_id": "laptop-1", "task_type": "LIGHTWEIGHT_QUERY"},
        )
        assert r3.status_code == 429
        assert "Task queue full" in r3.json()["detail"]


@pytest.mark.asyncio
async def test_dispatcher_automatic_failover_when_worker_fails() -> None:
    """When dispatching to worker-1 fails, dispatcher evicts worker-1, re-solves, and completes on worker-2."""
    attempts_by_host: dict[str, int] = {}

    def mock_worker_handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        attempts_by_host[host] = attempts_by_host.get(host, 0) + 1
        if host == "10.128.0.11":
            # Simulate worker-1 crashing / returning 503
            return httpx.Response(503, json={"error": "worker crashed"})
        return httpx.Response(
            200,
            json={
                "task_id": "tsk-1",
                "worker_id": "worker-2",
                "status": "COMPLETED",
                "execution_ms": 18.5,
                "matrix_dim": 1000,
                "checksum": 1.23,
            },
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_worker_handler))
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        dispatch_max_retries=1,
    )
    app = create_app(settings=cfg, worker_http_client=mock_http)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://controller") as client:
        # Register worker-1 (lower CPU so MILP picks it first) and worker-2 (backup)
        await client.post(
            "/api/v1/telemetry",
            json={
                "worker_id": "worker-1",
                "ip_address": "10.128.0.11",
                "port": 8001,
                "cpu_percent": 10.0,
                "memory_total_mb": 4096.0,
                "memory_used_mb": 512.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.2,
                "active_task_count": 0,
            },
        )
        await client.post(
            "/api/v1/telemetry",
            json={
                "worker_id": "worker-2",
                "ip_address": "10.128.0.12",
                "port": 8001,
                "cpu_percent": 30.0,
                "memory_total_mb": 4096.0,
                "memory_used_mb": 512.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.6,
                "active_task_count": 0,
            },
        )

        # Submit task; MILP assigns to worker-1 (10% CPU), which fails twice (initial + 1 retry),
        # then dispatcher evicts worker-1, re-solves onto worker-2, and succeeds!
        sub = await client.post(
            "/api/v1/tasks",
            json={"client_id": "laptop-failover", "task_type": "LIGHTWEIGHT_QUERY"},
        )
        assert sub.status_code == 202

        await app.state.batcher.flush_one_batch(wait_for_dispatch=True)

        # Verify worker-1 was retried and then evicted, and task completed on worker-2
        assert attempts_by_host.get("10.128.0.11") == 2
        assert attempts_by_host.get("10.128.0.12") == 1

        active_workers = await app.state.cluster_state.get_active_workers()
        assert [w.worker_id for w in active_workers] == ["worker-2"]

        recent = await client.get("/api/v1/tasks/recent")
        latest = recent.json()[0]
        assert latest["status"] == "COMPLETED"
        assert latest["assigned_worker_id"] == "worker-2"

        # Test kill and revive endpoints
        kill_r = await client.post("/api/v1/control/workers/worker-2/kill")
        assert kill_r.status_code == 200
        assert await app.state.cluster_state.get_active_workers() == []

        rev_r = await client.post("/api/v1/control/workers/worker-2/revive")
        assert rev_r.status_code == 200

        # Test benchmark runs endpoint
        bench_r = await client.get("/api/v1/benchmark/runs")
        assert bench_r.status_code == 200
        runs = bench_r.json()
        assert len(runs) >= 1
        assert "ortools_milp" in runs[0]["results"]

    await mock_http.aclose()


def test_websocket_cluster_snapshot_stream() -> None:
    """Verify WebSocket `/ws` immediately sends a valid CLUSTER_SNAPSHOT and responds to ping."""
    cfg = Settings(local_mode=True, seed_demo_workers=True)
    app = create_app(settings=cfg)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        initial_msg = ws.receive_json()
        assert initial_msg["type"] == "CLUSTER_SNAPSHOT"
        assert "workers" in initial_msg
        assert "recent_assignments" in initial_msg
        assert "clients" in initial_msg
        assert initial_msg["active_scheduler"] == "ortools_milp"

        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "PONG"

