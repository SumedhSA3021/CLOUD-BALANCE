"""Runtime Control Endpoints (Scheduler Hot-Swap, Spike Injection, Worker Failover Simulation)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.security import verify_admin_token
from app.models.schemas import (
    ClusterSnapshot,
    SchedulerControlRequest,
    TrafficControlRequest,
)
from app.schedulers.ortools_milp import get_solver_call_count, reset_solver_call_count
from app.schedulers.test_hooks import is_test_running
from app.services.broadcaster import WebSocketBroadcaster
from app.services.cluster_state import ClusterStateService
from app.services.scheduler_state import SchedulerStateService

router = APIRouter(
    prefix="/api/v1/control",
    tags=["control"],
    dependencies=[Depends(verify_admin_token)],
)


@router.post("/scheduler")
async def switch_scheduler(
    payload: SchedulerControlRequest,
    request: Request,
) -> dict[str, Any]:
    """Hot-swap the active scheduling algorithm at runtime (`ortools_milp`, `round_robin`)."""
    if is_test_running():
        raise HTTPException(
            status_code=409,
            detail="Cannot change scheduling mode while an automated test is running (mode is locked).",
        )
    scheduler_state: SchedulerStateService = request.app.state.scheduler_state
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster
    redis_client = request.app.state.redis_client
    active = scheduler_state.set_scheduler(payload.scheduler)
    mode_val = "round_robin" if active == "round_robin" else "milp"
    await redis_client.set("sched_mode", mode_val)
    if mode_val == "round_robin":
        await redis_client.set("rr_counter", "0")
    await broadcaster.broadcast_now()
    return {
        "status": "updated",
        "active_scheduler": active,
    }


@router.get("/solver-metrics")
async def get_solver_metrics() -> dict[str, Any]:
    """Retrieve cumulative OR-Tools solver call count."""
    return {"solver_call_count": get_solver_call_count()}


@router.post("/solver-metrics/reset")
async def reset_solver_metrics() -> dict[str, Any]:
    """Reset OR-Tools solver call count to 0."""
    reset_solver_call_count()
    return {"status": "reset", "solver_call_count": 0}


@router.post("/traffic")
async def control_traffic(
    payload: TrafficControlRequest,
    request: Request,
) -> dict[str, Any]:
    """Adjust configured global lambda or inject a burst spike."""
    scheduler_state: SchedulerStateService = request.app.state.scheduler_state
    broadcaster: WebSocketBroadcaster = request.app.state.broadcaster

    if payload.lambda_rate is not None:
        scheduler_state.set_configured_lambda(payload.lambda_rate)

    injected = 0
    if payload.spike_tasks:
        from app.api.tasks import TaskContractRequest, execute_task_contract

        for _ in range(payload.spike_tasks):
            await execute_task_contract(
                TaskContractRequest(
                    client_id=payload.spike_client_id,
                    task_type=payload.spike_task_type.value,
                ),
                request,
            )
            injected += 1

    await broadcaster.broadcast_now()
    return {
        "status": "ok",
        "configured_lambda": scheduler_state.configured_lambda,
        "injected_spike_tasks": injected,
        "queue_depth": scheduler_state.queue_depth,
    }


@router.post("/workers/{worker_id}/kill")
async def kill_worker_node(
    worker_id: str,
    request: Request,
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

