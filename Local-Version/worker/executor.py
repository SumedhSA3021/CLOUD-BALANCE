"""FastAPI Worker Executor (:8001) running real NumPy matrix workloads."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field


class ExecuteTaskRequest(BaseModel):
    """Inbound payload dispatched from Controller to POST /execute."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    duration_sec: float = Field(..., gt=0.0, le=60.0)
    matrix_dim: int = Field(..., ge=10, le=10000)
    cpu_demand_pct: float = Field(default=25.0, ge=0.0, le=100.0)
    mem_demand_mb: float = Field(default=256.0, ge=0.0)


class ExecuteTaskResponse(BaseModel):
    """Response returned to Controller upon completing np.dot execution."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    worker_id: str
    status: str = "COMPLETED"
    execution_ms: float
    matrix_dim: int
    checksum: float
    active_task_count: int


@dataclass
class WorkerRuntimeState:
    """Mutable runtime state for a single Worker Executor process."""

    worker_id: str = field(default_factory=lambda: os.getenv("WORKER_ID", "worker-1"))
    ip_address: str = field(default_factory=lambda: os.getenv("WORKER_IP", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("WORKER_PORT", "8001")))
    total_mem_mb: float = field(
        default_factory=lambda: float(os.getenv("WORKER_TOTAL_MEM_MB", "4096.0"))
    )
    base_cpu_pct: float = field(
        default_factory=lambda: float(os.getenv("WORKER_BASE_CPU_PCT", "8.0"))
    )
    base_mem_mb: float = field(
        default_factory=lambda: float(os.getenv("WORKER_BASE_MEM_MB", "420.0"))
    )
    time_scale: float = field(
        default_factory=lambda: float(os.getenv("WORKER_TIME_SCALE", "0.15"))
    )
    max_physical_dim: int = field(
        default_factory=lambda: int(os.getenv("WORKER_MAX_PHYSICAL_DIM", "350"))
    )
    active_task_count: int = 0
    active_cpu_demand_pct: float = 0.0
    active_mem_demand_mb: float = 0.0
    total_completed: int = 0


def _run_numpy_dot_kernel(
    physical_dim: int,
    target_duration_sec: float,
    seed: int,
) -> float:
    """Execute real NumPy matrix multiplication (`np.dot`) for `target_duration_sec`."""
    rng = np.random.default_rng(seed)
    a = rng.standard_normal((physical_dim, physical_dim), dtype=np.float64)
    b = rng.standard_normal((physical_dim, physical_dim), dtype=np.float64)

    deadline = time.perf_counter() + target_duration_sec
    checksum = 0.0
    iterations = 0
    while True:
        c = np.dot(a, b)
        checksum += float(c[0, 0])
        iterations += 1
        if time.perf_counter() >= deadline or iterations >= 25:
            break
    return round(checksum, 6)


def create_worker_app(state: WorkerRuntimeState | None = None) -> FastAPI:
    """Create FastAPI application for the internal Worker Executor."""
    runtime = state if state is not None else WorkerRuntimeState()
    enable_agent = os.getenv("WORKER_ENABLE_AGENT", "false").lower() in ("1", "true", "yes")
    controller_url = os.getenv("CONTROLLER_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = os.getenv("CB_API_KEY")

    async def _push_live_telemetry() -> None:
        if not enable_agent:
            return
        from worker.agent import sample_worker_telemetry

        payload = sample_worker_telemetry(
            worker_id=runtime.worker_id,
            ip_address=runtime.ip_address,
            port=runtime.port,
            runtime_state=runtime,
            virtual_profile=True,
        )
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    f"{controller_url}/api/v1/telemetry",
                    json=payload,
                    headers=headers,
                )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        agent_task: asyncio.Task[None] | None = None
        if enable_agent:
            from worker.agent import WorkerTelemetryAgent

            agent = WorkerTelemetryAgent(
                worker_id=runtime.worker_id,
                ip_address=runtime.ip_address,
                port=runtime.port,
                controller_url=controller_url,
                interval_sec=float(os.getenv("WORKER_TELEMETRY_INTERVAL", "1.5")),
                api_key=api_key,
                runtime_state=runtime,
                virtual_profile=True,
            )
            agent_task = asyncio.create_task(agent.run_forever())
        try:
            yield
        finally:
            if agent_task is not None:
                agent_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await agent_task

    app = FastAPI(
        title=f"CloudBalance Worker Executor ({runtime.worker_id})",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "worker_id": runtime.worker_id,
            "active_task_count": runtime.active_task_count,
            "total_completed": runtime.total_completed,
        }

    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        return {
            "worker_id": runtime.worker_id,
            "ip_address": runtime.ip_address,
            "port": runtime.port,
            "active_task_count": runtime.active_task_count,
            "active_cpu_demand_pct": round(runtime.active_cpu_demand_pct, 2),
            "active_mem_demand_mb": round(runtime.active_mem_demand_mb, 2),
            "total_mem_mb": runtime.total_mem_mb,
            "base_cpu_pct": runtime.base_cpu_pct,
            "base_mem_mb": runtime.base_mem_mb,
            "total_completed": runtime.total_completed,
        }

    @app.post("/execute", response_model=ExecuteTaskResponse)
    async def execute_workload(req: ExecuteTaskRequest) -> ExecuteTaskResponse:
        start_ns = time.perf_counter_ns()
        runtime.active_task_count += 1
        runtime.active_cpu_demand_pct += req.cpu_demand_pct
        runtime.active_mem_demand_mb += req.mem_demand_mb
        await _push_live_telemetry()

        try:
            physical_dim = max(16, min(req.matrix_dim, runtime.max_physical_dim))
            effective_duration = max(0.01, req.duration_sec * runtime.time_scale)
            seed = abs(hash(req.task_id)) % (2**31 - 1)

            checksum = await asyncio.to_thread(
                _run_numpy_dot_kernel,
                physical_dim,
                effective_duration,
                seed,
            )
            runtime.total_completed += 1
        finally:
            runtime.active_task_count = max(0, runtime.active_task_count - 1)
            runtime.active_cpu_demand_pct = max(
                0.0, runtime.active_cpu_demand_pct - req.cpu_demand_pct
            )
            runtime.active_mem_demand_mb = max(
                0.0, runtime.active_mem_demand_mb - req.mem_demand_mb
            )
            await _push_live_telemetry()

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        return ExecuteTaskResponse(
            task_id=req.task_id,
            worker_id=runtime.worker_id,
            status="COMPLETED",
            execution_ms=round(elapsed_ms, 2),
            matrix_dim=req.matrix_dim,
            checksum=checksum,
            active_task_count=runtime.active_task_count,
        )

    return app


app = create_worker_app()

