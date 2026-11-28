"""Runtime Control Endpoints (Scheduler Hot-Swap, Spike Injection, Worker Failover Simulation)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.security import verify_api_key
from app.models.schemas import (
    ClusterSnapshot,
    SchedulerControlRequest,
    Task,
    TaskRequest,
    TrafficControlRequest,
)
from app.services.batcher import MicroBatcherService
from app.services.broadcaster import WebSocketBroadcaster
from app.services.cluster_state import ClusterStateService

router = APIRouter(prefix="/api/v1/control", tags=["control"])


@router.post("/scheduler")
async def switch_scheduler(
    payload: SchedulerControlRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Hot-swap the active scheduling algorithm at runtime (`ortools_milp`, `round_robin`, `least_connections`)."""
    batcher: MicroBatcherService = request.app.state.batcher
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster
    active = batcher.set_scheduler(payload.scheduler)
    await broadcaster.broadcast_now()
    return {
        "status": "updated",
        "active_scheduler": active,
    }


@router.post("/traffic")
async def control_traffic(
    payload: TrafficControlRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Adjust configured global lambda, pause/resume micro-batcher, or inject a burst spike."""
    batcher: MicroBatcherService = request.app.state.batcher
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster

    if payload.lambda_rate is not None:
        batcher.set_configured_lambda(payload.lambda_rate)
    if payload.paused is not None:
        batcher.set_paused(payload.paused)

    injected = 0
    if payload.spike_tasks:
        for _ in range(payload.spike_tasks):
            t_req = TaskRequest(
                client_id=payload.spike_client_id,
                task_type=payload.spike_task_type,
            )
            batcher.enqueue(Task.from_request(t_req))
            injected += 1

    await broadcaster.broadcast_now()
    return {
        "status": "ok",
        "configured_lambda": batcher.configured_lambda,
        "paused": batcher.paused,
        "injected_spike_tasks": injected,
        "queue_depth": batcher.queue_depth,
    }


@router.post("/workers/{worker_id}/kill")
async def kill_worker_node(
    worker_id: str,
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Simulate worker failure by expiring its Redis key and blocking heartbeats."""
    cluster_state: ClusterStateService = request.app.state.cluster_state
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster
    await cluster_state.kill_worker(worker_id)
    await broadcaster.broadcast_now()
    return {"status": "killed", "worker_id": worker_id}


@router.post("/workers/{worker_id}/revive")
async def revive_worker_node(
    worker_id: str,
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Revive a simulated-dead worker node."""
    cluster_state: ClusterStateService = request.app.state.cluster_state
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster
    await cluster_state.revive_worker(worker_id)
    if request.app.state.settings.seed_demo_workers:
        await cluster_state.seed_virtual_workers_if_empty(force_missing=True)
    await broadcaster.broadcast_now()
    return {"status": "revived", "worker_id": worker_id}


@router.get("/snapshot", response_model=ClusterSnapshot)
async def get_current_snapshot(request: Request) -> ClusterSnapshot:
    """HTTP fallback returning the exact same `ClusterSnapshot` as the WebSocket broadcast."""
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster
    return await broadcaster.build_snapshot()

