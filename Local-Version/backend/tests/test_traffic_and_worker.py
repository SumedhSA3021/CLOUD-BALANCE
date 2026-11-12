"""Unit and Integration Tests for Phase 2: Poisson Traffic Generator and Worker Executor/Agent."""

from __future__ import annotations

import statistics

import httpx
import pytest
from traffic.cli import main as cli_main
from traffic.poisson_generator import (
    ClientStreamConfig,
    PoissonTrafficGenerator,
    superpose_seeded_streams,
)
from traffic.workloads import ScenarioType, WorkloadMix, compute_scenario_lambda
from worker.agent import WorkerTelemetryAgent, sample_worker_telemetry
from worker.executor import WorkerRuntimeState, create_worker_app

from app.models.schemas import Telemetry


def test_poisson_generator_reproducibility_and_exponential_mean() -> None:
    """Verify seeded Poisson stream is 100% deterministic and mean dt converges to 1/lambda."""
    gen1 = PoissonTrafficGenerator(
        client_id="laptop-a",
        lambda_rate=10.0,
        mix=WorkloadMix.CPU,
        scenario=ScenarioType.STEADY,
        seed=12345,
    )
    gen2 = PoissonTrafficGenerator(
        client_id="laptop-a",
        lambda_rate=10.0,
        mix=WorkloadMix.CPU,
        scenario=ScenarioType.STEADY,
        seed=12345,
    )

    trace1 = gen1.generate_trace(max_tasks=500)
    trace2 = gen2.generate_trace(max_tasks=500)
    assert trace1 == trace2

    mean_dt = statistics.mean(ev.inter_arrival_sec for ev in trace1)
    # Theoretical mean is 1 / 10.0 = 0.10s; with N=500 should be well within [0.08, 0.12]
    assert 0.08 <= mean_dt <= 0.12

    # Verify CPU mix dominance (>50% CPU_INTENSIVE)
    cpu_count = sum(1 for ev in trace1 if ev.task_type == "CPU_INTENSIVE")
    assert cpu_count > 250


def test_superposition_of_independent_poisson_streams() -> None:
    """Verify superposing 3 client streams merges in chronological order with combined rate."""
    configs = [
        ClientStreamConfig(
            client_id="laptop-a",
            base_lambda=4.0,
            mix=WorkloadMix.CPU,
            scenario=ScenarioType.STEADY,
            max_tasks=40,
            seed=101,
        ),
        ClientStreamConfig(
            client_id="laptop-b",
            base_lambda=3.0,
            mix=WorkloadMix.MEM,
            scenario=ScenarioType.STEADY,
            max_tasks=30,
            seed=202,
        ),
        ClientStreamConfig(
            client_id="laptop-c",
            base_lambda=5.0,
            mix=WorkloadMix.BALANCED,
            scenario=ScenarioType.BURST,
            max_tasks=50,
            seed=303,
        ),
    ]
    merged = superpose_seeded_streams(configs)
    assert len(merged) == 120
    # Strictly non-decreasing arrival timestamps
    for i in range(1, len(merged)):
        assert merged[i].arrival_time_sec >= merged[i - 1].arrival_time_sec
    assert {ev.client_id for ev in merged} == {"laptop-a", "laptop-b", "laptop-c"}


def test_scenario_lambda_modulation_and_live_update() -> None:
    """Verify steady, burst, and ramp scenarios and live set_lambda."""
    assert compute_scenario_lambda(5.0, ScenarioType.STEADY, 3.0) == 5.0
    assert compute_scenario_lambda(5.0, ScenarioType.BURST, 7.0) == 15.0
    assert compute_scenario_lambda(5.0, ScenarioType.RAMP, 15.0, 20.0) == 12.5

    gen = PoissonTrafficGenerator(lambda_rate=4.0, seed=7)
    gen.set_lambda(8.0)
    assert gen.lambda_rate == 8.0


def test_traffic_cli_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify `cb-traffic --dry-run` CLI execution."""
    rc = cli_main(
        [
            "--client-id",
            "laptop-cli",
            "--lambda",
            "6.0",
            "--max-tasks",
            "15",
            "--seed",
            "99",
            "--mix",
            "mem",
            "--scenario",
            "burst",
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    assert '"client_id": "laptop-cli"' in captured
    assert '"total_events": 15' in captured


@pytest.mark.asyncio
async def test_worker_executor_runs_real_numpy_workload_and_telemetry() -> None:
    """Verify Worker FastAPI `/execute` runs real np.dot and `sample_worker_telemetry` validates."""
    state = WorkerRuntimeState(
        worker_id="worker-test-1",
        ip_address="10.128.0.21",
        port=8001,
        time_scale=0.02,
        max_physical_dim=120,
    )
    worker_app = create_worker_app(state)

    transport = httpx.ASGITransport(app=worker_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://worker-test") as client:
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["worker_id"] == "worker-test-1"

        exec_resp = await client.post(
            "/execute",
            json={
                "task_id": "tsk-np-001",
                "duration_sec": 1.5,
                "matrix_dim": 1000,
                "cpu_demand_pct": 35.0,
                "mem_demand_mb": 256.0,
            },
        )
        assert exec_resp.status_code == 200
        data = exec_resp.json()
        assert data["task_id"] == "tsk-np-001"
        assert data["worker_id"] == "worker-test-1"
        assert data["status"] == "COMPLETED"
        assert data["execution_ms"] > 0
        assert isinstance(data["checksum"], float)
        assert state.total_completed == 1
        assert state.active_task_count == 0

        metrics_resp = await client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert metrics_resp.json()["total_completed"] == 1

    # Validate psutil telemetry sampling matches backend Telemetry schema
    raw_telemetry = sample_worker_telemetry(
        worker_id="worker-test-1",
        ip_address="10.128.0.21",
        port=8001,
        runtime_state=state,
        virtual_profile=True,
    )
    parsed = Telemetry.model_validate(raw_telemetry)
    assert parsed.worker_id == "worker-test-1"
    assert 0.0 <= parsed.cpu_percent <= 100.0
    assert parsed.memory_total_mb == 4096.0


@pytest.mark.asyncio
async def test_telemetry_agent_posts_to_mock_controller() -> None:
    """Verify WorkerTelemetryAgent sends valid telemetry payloads over HTTP."""
    received: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        received.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"ok": True})

    state = WorkerRuntimeState(worker_id="worker-agent-1")
    agent = WorkerTelemetryAgent(
        worker_id="worker-agent-1",
        ip_address="127.0.0.1",
        port=8001,
        controller_url="http://controller.local",
        runtime_state=state,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await agent.send_once(client)
        assert ok is True
        assert len(received) == 1
        assert received[0]["worker_id"] == "worker-agent-1"
