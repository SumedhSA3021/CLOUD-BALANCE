"""FastAPI Worker Executor (:8001) executing CGPA, heavy hashing, and compute workloads."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

# Maximum allowed payload size: 64 KB default
MAX_PAYLOAD_BYTES = int(os.getenv("MAX_PAYLOAD_BYTES", str(64 * 1024)))

# Default iterations for heavy hashing loop: tuned for 0.5 - 1.0s on e2-micro
DEFAULT_HEAVY_ITERATIONS = int(os.getenv("HEAVY_TASK_ITERATIONS", "180000"))


class ExecuteTaskRequest(BaseModel):
    """Inbound payload dispatched to Worker POST /execute."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    task_id: str = Field(default_factory=lambda: f"tsk-{uuid.uuid4().hex[:10]}")
    task_type: str = Field(default="legacy", description="'light', 'heavy', or legacy matrix workloads")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task specific parameters")

    # Backward compatibility fields for controller cluster
    duration_sec: float = Field(default=0.1, gt=0.0, le=60.0)
    matrix_dim: int = Field(default=100, ge=10, le=10000)
    cpu_demand_pct: float = Field(default=25.0, ge=0.0, le=100.0)
    mem_demand_mb: float = Field(default=256.0, ge=0.0)


class ExecuteTaskResponse(BaseModel):
    """Response returned upon completing worker task execution."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    worker_id: str
    task_type: str = "legacy"
    status: str = "COMPLETED"
    execution_ms: float
    result: dict[str, Any] = Field(default_factory=dict)
    active_task_count: int = 0
    matrix_dim: int = 0
    checksum: float = 0.0


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


def _calculate_cgpa(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate CGPA from request payload courses or grades (task_type == 'light')."""
    courses = payload.get("courses")
    grades = payload.get("grades")
    credits_list = payload.get("credits")

    if not courses and not grades:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must contain 'courses' or 'grades' list for light CGPA task",
        )

    total_weighted_points = 0.0
    total_credits = 0.0
    course_count = 0

    if courses:
        if not isinstance(courses, list):
            raise HTTPException(status_code=400, detail="'courses' must be a list")
        if len(courses) > 500:
            raise HTTPException(status_code=400, detail="Too many courses (max 500)")
        for item in courses:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Course items must be dictionaries")
            grade = item.get("grade", item.get("grade_point", item.get("gpa")))
            cr = item.get("credits", item.get("credit", 1.0))
            if grade is None:
                raise HTTPException(status_code=400, detail="Course missing 'grade'")
            try:
                g_val = float(grade)
                c_val = float(cr)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Grade and credits must be numeric")
            if not (0.0 <= g_val <= 10.0):
                raise HTTPException(status_code=400, detail=f"Grade {g_val} must be between 0.0 and 10.0")
            if c_val <= 0.0:
                raise HTTPException(status_code=400, detail="Credits must be positive")
            total_weighted_points += g_val * c_val
            total_credits += c_val
            course_count += 1
    elif grades:
        if not isinstance(grades, list):
            raise HTTPException(status_code=400, detail="'grades' must be a list")
        if len(grades) > 500:
            raise HTTPException(status_code=400, detail="Too many grades (max 500)")
        cr_arr = (
            credits_list
            if (credits_list and isinstance(credits_list, list) and len(credits_list) == len(grades))
            else [1.0] * len(grades)
        )
        for g, c in zip(grades, cr_arr):
            try:
                g_val = float(g)
                c_val = float(c)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Grade and credits must be numeric")
            if not (0.0 <= g_val <= 10.0):
                raise HTTPException(status_code=400, detail=f"Grade {g_val} must be between 0.0 and 10.0")
            if c_val <= 0.0:
                raise HTTPException(status_code=400, detail="Credits must be positive")
            total_weighted_points += g_val * c_val
            total_credits += c_val
            course_count += 1

    if total_credits <= 0.0:
        raise HTTPException(status_code=400, detail="Total credits must be greater than zero")

    cgpa = total_weighted_points / total_credits
    return {
        "cgpa": round(cgpa, 2),
        "total_credits": round(total_credits, 2),
        "course_count": course_count,
        "scale": 10.0,
    }


def _run_heavy_hashing_loop(payload: dict[str, Any], default_iterations: int) -> dict[str, Any]:
    """Perform iterative SHA-256 hashing loop tuned for 0.5-1.0s on e2-micro."""
    raw_data = str(payload.get("data", "cloudbalance-workload-seed-string"))
    requested_iter = payload.get("iterations")
    if requested_iter is not None:
        try:
            iterations = int(requested_iter)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Iterations must be an integer")
        if iterations <= 0:
            raise HTTPException(status_code=400, detail="Iterations must be positive")
        if iterations > 3_000_000:
            raise HTTPException(status_code=400, detail="Iterations exceeds safe limit (max 3,000,000)")
    else:
        iterations = default_iterations

    current_hash = hashlib.sha256(raw_data.encode("utf-8")).digest()
    for _ in range(iterations):
        current_hash = hashlib.sha256(current_hash).digest()

    return {
        "final_hash": current_hash.hex(),
        "iterations": iterations,
        "algorithm": "sha256",
        "input_preview": raw_data[:32],
    }


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
    async def execute_workload(req: ExecuteTaskRequest, request: Request) -> ExecuteTaskResponse:
        # 3. Reject payload sizes above a safe limit with a clear 4xx error.
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_PAYLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Payload size ({content_length} bytes) exceeds maximum safe limit of {MAX_PAYLOAD_BYTES} bytes",
            )
        if len(str(req.payload)) > MAX_PAYLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Payload size exceeds maximum safe limit of {MAX_PAYLOAD_BYTES} bytes",
            )

        start_ns = time.perf_counter_ns()
        runtime.active_task_count += 1
        runtime.active_cpu_demand_pct += req.cpu_demand_pct
        runtime.active_mem_demand_mb += req.mem_demand_mb
        await _push_live_telemetry()

        task_type = (req.task_type or "legacy").lower()
        checksum = 0.0
        result: dict[str, Any] = {}

        try:
            # 1. task_type "light": CGPA calculation
            if task_type in ("light", "cgpa"):
                result = _calculate_cgpa(req.payload)
                checksum = float(result.get("cgpa", 0.0))

            # 2. task_type "heavy": hashing loop with configurable iterations
            elif task_type in ("heavy", "hash", "hashing"):
                result = await asyncio.to_thread(
                    _run_heavy_hashing_loop,
                    req.payload,
                    DEFAULT_HEAVY_ITERATIONS,
                )
                checksum = float(int(result["final_hash"][:8], 16))

            # Legacy compute workload (np.dot)
            else:
                physical_dim = max(16, min(req.matrix_dim, runtime.max_physical_dim))
                effective_duration = max(0.01, req.duration_sec * runtime.time_scale)
                seed = abs(hash(req.task_id)) % (2**31 - 1)

                checksum = await asyncio.to_thread(
                    _run_numpy_dot_kernel,
                    physical_dim,
                    effective_duration,
                    seed,
                )
                result = {"matrix_dim": req.matrix_dim, "checksum": checksum}

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

        # 4. Return result plus exec_ms measured inside the worker.
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        return ExecuteTaskResponse(
            task_id=req.task_id,
            worker_id=runtime.worker_id,
            task_type=task_type,
            status="COMPLETED",
            execution_ms=round(elapsed_ms, 2),
            result=result,
            matrix_dim=req.matrix_dim,
            checksum=checksum,
            active_task_count=runtime.active_task_count,
        )

    return app


app = create_worker_app()

