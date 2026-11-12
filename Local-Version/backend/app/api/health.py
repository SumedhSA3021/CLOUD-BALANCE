"""Liveness (`/health`) and Readiness (`/ready`) Probes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.mongo_client import DualMongoClient
from app.core.redis_client import DualRedisClient
from app.services.batcher import MicroBatcherService
from app.services.cluster_state import ClusterStateService

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/api/v1/health")
async def health_check() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "cloudbalance-controller"}


@router.get("/ready")
@router.get("/api/v1/ready")
async def readiness_check(request: Request) -> dict[str, Any]:
    """Readiness probe checking Redis, MongoDB/SQLite, active workers, and scheduler."""
    redis_client: DualRedisClient = request.app.state.redis_client
    mongo_client: DualMongoClient = request.app.state.mongo_client
    cluster_state: ClusterStateService = request.app.state.cluster_state
    batcher: MicroBatcherService = request.app.state.batcher

    redis_ok = await redis_client.ping()
    mongo_ok = await mongo_client.ping()
    workers = await cluster_state.get_active_workers()

    return {
        "ready": bool(redis_ok and mongo_ok),
        "redis_backend": redis_client.backend_mode,
        "persistence_backend": mongo_client.backend_mode,
        "active_workers": len(workers),
        "active_scheduler": batcher.active_scheduler_name,
        "queue_depth": batcher.queue_depth,
    }

