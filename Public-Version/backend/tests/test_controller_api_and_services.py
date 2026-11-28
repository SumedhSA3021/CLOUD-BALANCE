"""End-to-End Integration Tests for Phase 3: Controller Services, Failover, Backpressure, and WebSocket."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.mark.asyncio
async def test_controller_task_flow_telemetry_and_scheduler_hotswap() -> None:
    """Verify telemetry ingestion, task submission, and scheduler hot-swap."""
    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        max_queue_depth=10,
    )
    app = create_app(settings=cfg)
    admin_headers = {"Authorization": f"Bearer {cfg.admin_token}"}
    worker_headers = {"X-Worker-Secret": cfg.worker_secret}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://controller") as client:
        # 1. Health & Ready probes (including /healthz)
        h_resp = await client.get("/health")
        assert h_resp.status_code == 200
        assert h_resp.headers.get("X-Correlation-ID")
        hz_resp = await client.get("/healthz")
        assert hz_resp.status_code == 200 and hz_resp.json()["status"] == "ok"

        r_resp = await client.get("/ready")
        assert r_resp.status_code == 200
        assert r_resp.json()["ready"] is True

        # 2. Post telemetry for 2 virtual workers (requires WORKER_SECRET)
        for wid, cpu in (("worker-1", 15.0), ("worker-2", 40.0)):
            t_resp = await client.post(
                "/api/v1/telemetry",
                headers=worker_headers,
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

        assert (await client.get("/api/v1/telemetry/workers")).status_code == 401
        w_resp = await client.get("/api/v1/telemetry/workers", headers=admin_headers)
        assert len(w_resp.json()) == 2

        # 3. Submit 3 tasks from different client laptops via unified pipeline
        for cid, ttype in (
            ("laptop-a", "CPU_INTENSIVE"),
            ("laptop-b", "MEMORY_INTENSIVE"),
            ("laptop-c", "LIGHTWEIGHT_QUERY"),
        ):
            sub_resp = await client.post(
                "/tasks",
                json={"client_id": cid, "task_type": ttype},
            )
            assert sub_resp.status_code == 200
            assert sub_resp.json()["assigned_worker"] in ("worker-1", "worker-2")

        assert (await client.get("/api/v1/control/snapshot")).status_code == 401
        snap_init = await client.get("/api/v1/control/snapshot", headers=admin_headers)
        assert snap_init.status_code == 200
        recent_data = snap_init.json()["recent_assignments"]
        assert len(recent_data) == 3
        assert all(item["status"] == "COMPLETED" for item in recent_data)
        assert any(item["client_id"] == "laptop-a" for item in recent_data)

        # 4. Hot-swap scheduler to round_robin
        swap_resp = await client.post(
            "/api/v1/control/scheduler",
            headers=admin_headers,
            json={"scheduler": "round_robin"},
        )
        assert swap_resp.status_code == 200
        assert swap_resp.json()["active_scheduler"] == "round_robin"

        # 5. Traffic control: inject spike (routes through execute_task_contract)
        traf_resp = await client.post(
            "/api/v1/control/traffic",
            headers=admin_headers,
            json={
                "lambda_rate": 24.0,
                "spike_tasks": 3,
                "spike_client_id": "laptop-spike",
                "spike_task_type": "BALANCED_COMPUTE",
            },
        )
        assert traf_resp.status_code == 200
        assert traf_resp.json()["injected_spike_tasks"] == 3

        # 6. Verify snapshot endpoint reflects unified pipeline traffic
        snap_resp = await client.get("/api/v1/control/snapshot", headers=admin_headers)
        assert snap_resp.status_code == 200
        snap = snap_resp.json()
        assert snap["type"] == "CLUSTER_SNAPSHOT"
        assert len(snap["workers"]) == 2
        assert len(snap["clients"]) >= 3
        assert len(snap["recent_assignments"]) == 6


@pytest.mark.asyncio
async def test_worker_kill_revive_and_benchmark_runs() -> None:
    """Verify worker kill, revive, and benchmark runs endpoints."""
    cfg = Settings(local_mode=True, seed_demo_workers=False)
    app = create_app(settings=cfg)
    admin_headers = {"Authorization": f"Bearer {cfg.admin_token}"}
    worker_headers = {"X-Worker-Secret": cfg.worker_secret}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://controller") as client:
        await client.post(
            "/api/v1/telemetry",
            headers=worker_headers,
            json={
                "worker_id": "worker-2",
                "ip_address": "10.128.0.12",
                "port": 8002,
                "cpu_percent": 30.0,
                "memory_total_mb": 4096.0,
                "memory_used_mb": 512.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.6,
                "active_task_count": 0,
            },
        )
        kill_r = await client.post("/api/v1/control/workers/worker-2/kill", headers=admin_headers)
        assert kill_r.status_code == 200
        assert await app.state.cluster_state.get_active_workers() == []

        rev_r = await client.post("/api/v1/control/workers/worker-2/revive", headers=admin_headers)
        assert rev_r.status_code == 200

        assert (await client.get("/api/v1/benchmark/runs")).status_code == 401
        bench_r = await client.get("/api/v1/benchmark/runs", headers=admin_headers)
        assert bench_r.status_code == 200
        runs = bench_r.json()
        assert len(runs) >= 1
        assert "ortools_milp" in runs[0]["results"]


def test_websocket_cluster_snapshot_stream() -> None:
    """Verify WebSocket `/ws` rejects anonymous connections and streams snapshots with valid token."""
    cfg = Settings(local_mode=True, seed_demo_workers=True)
    app = create_app(settings=cfg)
    token = get_settings().admin_token if cfg.admin_token == get_settings().admin_token else cfg.admin_token

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
            pass

        with client.websocket_connect(f"/ws?token={token}") as ws:
            initial_msg = ws.receive_json()
            assert initial_msg["type"] == "CLUSTER_SNAPSHOT"
            assert "workers" in initial_msg
            assert "recent_assignments" in initial_msg
            assert "clients" in initial_msg
            assert initial_msg["active_scheduler"] == "ortools_milp"

            ws.send_text("ping")
            pong = ws.receive_json()
            assert pong["type"] == "PONG"

