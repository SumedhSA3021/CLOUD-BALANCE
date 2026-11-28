"""Worker Telemetry Ingestion Endpoint (`POST /api/v1/telemetry`)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.logging import get_logger
from app.core.redis_client import DualRedisClient
from app.core.security import verify_api_key
from app.models.schemas import Telemetry, WorkerSnapshotItem
from app.services.cluster_state import ClusterStateService

logger = get_logger("api.telemetry")
router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


def _get_cluster_state(request: Request) -> ClusterStateService:
    return request.app.state.cluster_state  # type: ignore[no-any-return]


def _get_redis(request: Request) -> DualRedisClient:
    return request.app.state.redis_client  # type: ignore[no-any-return]


@router.post("")
async def ingest_telemetry(
    payload: Telemetry,
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Receive worker psutil heartbeat and store in Redis with 10s TTL (`SETEX cluster:worker:{id} 10`)."""
    cluster_state = _get_cluster_state(request)
    accepted = await cluster_state.update_telemetry(payload)
    logger.info(
        "worker_telemetry_received",
        worker_id=payload.worker_id,
        cpu_percent=payload.cpu_percent,
        memory_percent=payload.memory_percent,
        active_task_count=payload.active_task_count,
        accepted=accepted,
    )
    return {
        "accepted": accepted,
        "worker_id": payload.worker_id,
        "ttl_seconds": 10,
    }


@router.get("/workers", response_model=list[WorkerSnapshotItem])
async def list_workers(request: Request) -> list[WorkerSnapshotItem]:
    """Return active worker snapshots with live + in-flight load."""
    cluster_state = _get_cluster_state(request)
    return await cluster_state.get_worker_snapshots()


@router.get("/redis")
async def inspect_redis_state(request: Request) -> dict[str, Any]:
    """Inspect all live keys in Redis (`cluster:worker:*`, `cluster:task:*`, `cluster:assignment:*`)."""
    redis_client = _get_redis(request)
    all_keys = await redis_client.keys("cluster:*")
    entries: dict[str, Any] = {}
    for key in all_keys:
        raw = await redis_client.get(key)
        ttl = await redis_client.ttl(key)
        if raw is not None:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            entries[key] = {"ttl_seconds": ttl, "value": parsed}
    return {
        "redis_backend_mode": redis_client.backend_mode,
        "total_keys": len(entries),
        "keys": entries,
    }

