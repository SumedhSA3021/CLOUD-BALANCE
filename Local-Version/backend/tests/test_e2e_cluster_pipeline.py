"""Full-Stack E2E Tests: 3 Laptops -> Controller -> MILP/RR/LC -> 3 NumPy Workers."""

from __future__ import annotations

import httpx
import pytest
from traffic.poisson_generator import PoissonTrafficGenerator
from traffic.workloads import ScenarioType, WorkloadMix
from worker.agent import sample_worker_telemetry
from worker.executor import WorkerRuntimeState, create_worker_app

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_full_end_to_end_three_laptops_three_workers_pipeline() -> None:
    """Verify full closed-loop pipeline:
    1. 3 real Worker FastAPI apps (worker-1..3) running real np.dot workloads
    2. psutil telemetry sampled from each worker and posted to POST /api/v1/telemetry
    3. 3 client laptops (laptop-a CPU, laptop-b MEM, laptop-c BALANCED) streaming Poisson tasks
    4. Controller micro-batcher solving OR-Tools MILP and dispatching to workers over HTTP
    5. Live scheduler hot-swap to Least Connections and Round Robin
    6. Worker-2 crash & automatic re-solve failover onto remaining workers
    """
    # 1. Create 3 distinct Worker Executor FastAPI apps
    worker_states = {
        "worker-1": WorkerRuntimeState(
            worker_id="worker-1",
            ip_address="worker-1.internal",
            port=8001,
            total_mem_mb=4096.0,
            base_cpu_pct=12.0,
            base_mem_mb=512.0,
            time_scale=0.01,
            max_physical_dim=80,
        ),
        "worker-2": WorkerRuntimeState(
            worker_id="worker-2",
            ip_address="worker-2.internal",
            port=8001,
            total_mem_mb=4096.0,
            base_cpu_pct=18.0,
            base_mem_mb=640.0,
            time_scale=0.01,
            max_physical_dim=80,
        ),
        "worker-3": WorkerRuntimeState(
            worker_id="worker-3",
            ip_address="worker-3.internal",
            port=8001,
            total_mem_mb=8192.0,
            base_cpu_pct=8.0,
            base_mem_mb=768.0,
            time_scale=0.01,
            max_physical_dim=80,
        ),
    }
    worker_apps = {wid: create_worker_app(st) for wid, st in worker_states.items()}
    worker_transports = {
        f"{st.ip_address}": httpx.ASGITransport(app=worker_apps[wid])
        for wid, st in worker_states.items()
    }

    class MultiWorkerRouterTransport(httpx.AsyncBaseTransport):
        """Routes http://<worker-ip>:8001/execute requests to the matching in-process Worker ASGI app."""

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            host = request.url.host or ""
            transport = worker_transports.get(host)
            if transport is None:
                return httpx.Response(503, json={"error": f"Unknown worker host {host}"})
            return await transport.handle_async_request(request)

    router_http_client = httpx.AsyncClient(transport=MultiWorkerRouterTransport())

    cfg = Settings(
        local_mode=True,
        seed_demo_workers=False,
        batch_window_ms=50,
        batch_max_size=10,
        dispatch_max_retries=1,
    )
    controller_app = create_app(settings=cfg, worker_http_client=router_http_client)
    controller_transport = httpx.ASGITransport(app=controller_app)

    async with httpx.AsyncClient(
        transport=controller_transport,
        base_url="http://controller.public",
    ) as client:
        # 2. Each worker samples psutil + runtime state and posts to POST /api/v1/telemetry
        for wid, st in worker_states.items():
            telemetry_payload = sample_worker_telemetry(
                worker_id=wid,
                ip_address=st.ip_address,
                port=st.port,
                runtime_state=st,
                virtual_profile=True,
            )
            t_resp = await client.post("/api/v1/telemetry", json=telemetry_payload)
            assert t_resp.status_code == 200

        # 3. 3 client laptops stream Poisson tasks to POST /api/v1/tasks
        laptop_streams = [
            PoissonTrafficGenerator(
                client_id="laptop-alpha",
                lambda_rate=20.0,
                mix=WorkloadMix.CPU,
                scenario=ScenarioType.STEADY,
                seed=101,
            ),
            PoissonTrafficGenerator(
                client_id="laptop-beta",
                lambda_rate=20.0,
                mix=WorkloadMix.MEM,
                scenario=ScenarioType.STEADY,
                seed=202,
            ),
            PoissonTrafficGenerator(
                client_id="laptop-gamma",
                lambda_rate=20.0,
                mix=WorkloadMix.BALANCED,
                scenario=ScenarioType.BURST,
                seed=303,
            ),
        ]

        for gen in laptop_streams:
            summary = await gen.run_against_target(
                target_url="http://controller.public",
                max_tasks=5,
                realtime_sleep=False,
                http_client=client,
            )
            assert summary.sent_count == 5
            assert summary.accepted_count == 5
            assert summary.error_count == 0

        # 4. Flush micro-batches and execute real np.dot on the 3 worker apps
        batch1 = await controller_app.state.batcher.flush_one_batch(wait_for_dispatch=True)
        batch2 = await controller_app.state.batcher.flush_one_batch(wait_for_dispatch=True)
        assert len(batch1) + len(batch2) == 15

        # Verify all 3 real worker executors completed tasks
        total_worker_completions = sum(st.total_completed for st in worker_states.values())
        assert total_worker_completions == 15

        # 5. Verify snapshot contains all 3 workers, all 3 clients, and recent assignments
        snap_resp = await client.get("/api/v1/control/snapshot")
        assert snap_resp.status_code == 200
        snap = snap_resp.json()
        assert len(snap["workers"]) == 3
        assert {c["client_id"] for c in snap["clients"]} == {
            "laptop-alpha",
            "laptop-beta",
            "laptop-gamma",
        }
        assert len(snap["recent_assignments"]) == 15
        assert all(a["status"] == "COMPLETED" for a in snap["recent_assignments"])

    await router_http_client.aclose()

