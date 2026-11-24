"""Task Submission and Recent Assignments Endpoints (`POST /api/v1/tasks`)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.core.logging import get_logger
from app.core.profiles import TASK_PROFILES
from app.core.redis_client import DualRedisClient
from app.core.security import verify_api_key
from app.models.schemas import Assignment, Task, TaskRequest, TaskSubmissionResponse, Telemetry
from app.services.batcher import MicroBatcherService
from app.services.history import HistoryService

WORKERS = ["worker-1", "worker-2", "worker-3"]

logger = get_logger("api.tasks")
router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _get_batcher(request: Request) -> MicroBatcherService:
    return request.app.state.batcher  # type: ignore[no-any-return]


def _get_history(request: Request) -> HistoryService:
    return request.app.state.history  # type: ignore[no-any-return]


def _get_redis(request: Request) -> DualRedisClient:
    return request.app.state.redis_client  # type: ignore[no-any-return]


@router.post("", response_model=TaskSubmissionResponse, status_code=202)
async def submit_task(
    payload: TaskRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> TaskSubmissionResponse:
    """Resolve client task_type via server-side profile table and route directly or via micro-batcher."""
    batcher = _get_batcher(request)
    redis_client = _get_redis(request)
    history = _get_history(request)

    # 1. Read sched_mode ONCE per task at arrival and store it as task.mode.
    # Never re-read a global flag later in the dispatch path.
    raw_mode = batcher.active_scheduler_name
    if payload.mode:
        sched_mode = payload.mode
    elif "round_robin" in raw_mode:
        sched_mode = "round_robin"
    elif "milp" in raw_mode:
        sched_mode = "milp"
    else:
        sched_mode = raw_mode

    task = Task.from_request(payload, mode=sched_mode)

    # 2. For task.mode == "round_robin": n = Redis INCR rr_counter; worker = WORKERS[(n-1) % 3]; set dispatch_seq = n; send directly to the worker.
    # 3. RR tasks must bypass the micro-batch buffer AND the MILP solver completely.
    if task.mode == "round_robin":
        n = await redis_client.incr("rr_counter")
        worker_id = WORKERS[(n - 1) % 3]

        task = task.model_copy(
            update={
                "dispatch_seq": n,
                "scheduler_used": "round_robin",
                "mode": "round_robin",
            }
        )

        client_stats = getattr(request.app.state, "client_stats", None)
        now_mono = time.monotonic()
        if client_stats is not None:
            client_stats.record_enqueue(task.client_id, now_mono)
            client_stats.record_assigned(task.client_id, worker_id, queue_wait_ms=0.0)

        # 5. Record scheduler_used (from task.mode) and dispatch_seq on the task so the logger can use them.
        assignment = Assignment(
            task_id=task.task_id,
            client_id=task.client_id,
            task_type=task.task_type,
            cpu_demand_pct=task.cpu_demand_pct,
            mem_demand_mb=task.mem_demand_mb,
            assigned_worker_id=worker_id,
            scheduler="round_robin",
            scheduler_used="round_robin",
            dispatch_seq=n,
            solver_latency_ms=0.0,
            queue_wait_ms=0.0,
            status="ASSIGNED",
            degraded=False,
            timestamp=datetime.now(UTC),
        )
        await history.record_assignment(assignment)

        await redis_client.setex(
            f"cluster:task:{task.task_id}",
            300,
            task.model_dump_json(),
        )

        # Resolve target worker telemetry descriptor for direct dispatch
        cluster_state = request.app.state.cluster_state
        workers = await cluster_state.get_active_workers()
        target_worker = next((w for w in workers if w.worker_id == worker_id), None)
        if target_worker is None:
            port_map = {"worker-1": 8001, "worker-2": 8002, "worker-3": 8003}
            is_virtual = bool(workers and all(w.ip_address == "virtual" for w in workers))
            target_worker = Telemetry(
                worker_id=worker_id,
                ip_address="virtual" if is_virtual else "127.0.0.1",
                port=port_map.get(worker_id, 8001),
                cpu_percent=15.0,
                memory_total_mb=4096.0,
                memory_used_mb=512.0,
                memory_percent=12.5,
                load_avg_1m=0.5,
                active_task_count=0,
            )

        dispatcher = request.app.state.dispatcher
        asyncio.create_task(dispatcher.dispatch_direct_rr(task, target_worker))

        client_host = request.client.host if request.client else "unknown"
        logger.info(
            "rr_task_dispatched_directly",
            task_id=task.task_id,
            client_id=task.client_id,
            client_ip=client_host,
            worker_id=worker_id,
            dispatch_seq=n,
            scheduler_used="round_robin",
        )

        return TaskSubmissionResponse(
            accepted=True,
            task_id=task.task_id,
            client_id=task.client_id,
            task_type=task.task_type,
            cpu_demand_pct=task.cpu_demand_pct,
            mem_demand_mb=task.mem_demand_mb,
            duration_sec=task.duration_sec,
            matrix_dim=task.matrix_dim,
            queue_depth=0,
            queued_at=task.queued_at,
            mode="round_robin",
            dispatch_seq=n,
            assigned_worker_id=worker_id,
        )

    # 4. Only task.mode == "milp" tasks enter the batch loop / OR-Tools solve.
    queue_depth = batcher.enqueue(task)

    # Mirror incoming task request into Redis (TTL 300s)
    await redis_client.setex(
        f"cluster:task:{task.task_id}",
        300,
        task.model_dump_json(),
    )
    client_host = request.client.host if request.client else "unknown"
    logger.info(
        "task_request_received",
        task_id=task.task_id,
        client_id=task.client_id,
        client_ip=client_host,
        task_type=task.task_type.value,
        cpu_demand_pct=task.cpu_demand_pct,
        mem_demand_mb=task.mem_demand_mb,
        queue_depth=queue_depth,
        mode=task.mode,
    )

    return TaskSubmissionResponse(
        accepted=True,
        task_id=task.task_id,
        client_id=task.client_id,
        task_type=task.task_type,
        cpu_demand_pct=task.cpu_demand_pct,
        mem_demand_mb=task.mem_demand_mb,
        duration_sec=task.duration_sec,
        matrix_dim=task.matrix_dim,
        queue_depth=queue_depth,
        queued_at=task.queued_at,
        mode=task.mode,
    )


@router.get("/submit", response_model=TaskSubmissionResponse, status_code=202)
async def submit_task_get_fallback(
    request: Request,
    client_id: str = Query(..., min_length=1, max_length=64),
    task_type: str = Query(...),
    _api_key: str = Depends(verify_api_key),
) -> TaskSubmissionResponse:
    """Idempotent GET fallback for mobile hotspot browsers when HTTP/1.1 POST socket resets."""
    from app.core.profiles import TaskType

    payload = TaskRequest(client_id=client_id, task_type=TaskType(task_type))
    return await submit_task(payload=payload, request=request, _api_key=_api_key)


@router.get("/recent", response_model=list[Assignment])
async def get_recent_tasks(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    client_id: str | None = Query(default=None),
) -> list[Assignment]:
    """Fetch recent task assignments (optionally filtered by `client_id` for the `/client` page)."""
    history = _get_history(request)
    return history.get_recent_assignments(limit=limit, client_id=client_id)


@router.get("/profiles")
async def get_task_profiles() -> dict[str, Any]:
    """Expose server-side resource profiles for dashboard and documentation inspection."""
    return {
        k.value: {
            "task_type": v.task_type.value,
            "cpu_demand_pct": v.cpu_demand_pct,
            "mem_demand_mb": v.mem_demand_mb,
            "matrix_dim": v.matrix_dim,
            "duration_sec": v.duration_sec,
            "description": v.description,
        }
        for k, v in TASK_PROFILES.items()
    }

