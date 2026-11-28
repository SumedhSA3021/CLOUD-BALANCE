"""Task Submission and Recent Assignments Endpoints (`POST /api/v1/tasks`)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.core.logging import get_logger
from app.core.profiles import TASK_PROFILES
from app.core.redis_client import DualRedisClient
from app.core.security import verify_api_key
from app.models.schemas import Assignment, Task, TaskRequest, TaskSubmissionResponse
from app.services.batcher import MicroBatcherService
from app.services.history import HistoryService

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
    """Resolve client task_type via server-side profile table and enqueue for micro-batching."""
    batcher = _get_batcher(request)
    redis_client = _get_redis(request)
    task = Task.from_request(payload)
    queue_depth = batcher.enqueue(task)

    # Mirror incoming task request into Redis (TTL 300s) so `redis-cli KEYS cluster:task:*`
    # and `/api/v1/telemetry/redis` show every single request in real time.
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

