"""Task Submission and Recent Assignments Endpoints (`POST /api/v1/tasks`, `POST /tasks`)."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.logger import log_task_record
from app.core.logging import get_logger
from app.core.profiles import TASK_PROFILES, resolve_task_profile
from app.core.redis_client import DualRedisClient
from app.core.security import verify_api_key
from app.models.schemas import Assignment, Task, TaskRequest, TaskSubmissionResponse, Telemetry
from app.schedulers.test_hooks import get_current_test_id, get_current_test_metadata
from app.services.batcher import MicroBatcherService
from app.services.history import HistoryService

WORKERS = ["worker-1", "worker-2", "worker-3"]

logger = get_logger("api.tasks")
router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
public_tasks_router = APIRouter(tags=["tasks"])


class TaskContractRequest(BaseModel):
    """Shared contract task request: client_id, task_type (light|heavy), size, sent_at."""

    model_config = ConfigDict(extra="ignore")

    client_id: str = Field(..., min_length=1, max_length=64)
    task_type: str = Field(default="light", description="'light' or 'heavy'")
    size: int | None = Field(default=None, description="Optional payload size or iterations")
    sent_at: float | str | None = Field(default=None, description="Client departure timestamp")
    payload: dict[str, Any] | None = Field(default=None, description="Optional custom task payload")


class TaskContractResponse(BaseModel):
    """Shared contract task response: result, assigned_worker, queue_ms, exec_ms, total_ms."""

    model_config = ConfigDict(extra="ignore")

    result: dict[str, Any] = Field(default_factory=dict)
    assigned_worker: str
    queue_ms: float
    exec_ms: float
    total_ms: float


def _get_batcher(request: Request) -> MicroBatcherService:
    return request.app.state.batcher  # type: ignore[no-any-return]


def _get_history(request: Request) -> HistoryService:
    return request.app.state.history  # type: ignore[no-any-return]


def _get_redis(request: Request) -> DualRedisClient:
    return request.app.state.redis_client  # type: ignore[no-any-return]


async def execute_task_contract(
    req: TaskContractRequest,
    request: Request,
) -> TaskContractResponse:
    """Execute C1 task contract: schedule, forward to worker, log to CSV, and return timings."""
    start_mono = time.monotonic()
    now_wall = round(time.time(), 3)
    sent_at_val = req.sent_at if req.sent_at is not None else now_wall

    batcher = _get_batcher(request)
    redis_client = _get_redis(request)
    cluster_state = request.app.state.cluster_state
    in_flight = request.app.state.in_flight_tracker

    task_id = f"tsk-{uuid.uuid4().hex[:10]}"
    t_type = (req.task_type or "light").lower().strip()

    # 1. Read sched_mode ONCE per task at arrival (from active test or Redis)
    test_meta = get_current_test_metadata()
    test_id = get_current_test_id()
    if test_meta and "mode" in test_meta:
        sched_mode = str(test_meta["mode"]).lower().strip()
    else:
        stored_mode = await redis_client.get("sched_mode")
        if stored_mode:
            sched_mode = stored_mode.lower().strip()
        else:
            raw = batcher.active_scheduler_name
            sched_mode = "round_robin" if "round_robin" in raw else "milp"

    # 2. Call the scheduler
    if sched_mode == "round_robin":
        n = await redis_client.incr("rr_counter")
        assigned_worker = WORKERS[(n - 1) % 3]
        dispatch_seq: int | str = n
        scheduler_used = "round_robin"
    else:
        # MILP scheduler: select worker using OR-Tools MILP model
        workers = await cluster_state.get_active_workers()
        if not workers:
            port_map = {"worker-1": 8001, "worker-2": 8002, "worker-3": 8003}
            workers = [
                Telemetry(
                    worker_id=w,
                    ip_address="127.0.0.1",
                    port=port_map.get(w, 8001),
                    cpu_percent=10.0,
                    memory_total_mb=4096.0,
                    memory_used_mb=512.0,
                    memory_percent=12.5,
                    load_avg_1m=0.5,
                    active_task_count=0,
                )
                for w in WORKERS
            ]
        if hasattr(batcher, "get_scheduler"):
            milp_sched = batcher.get_scheduler("ortools_milp")
        elif hasattr(batcher, "_schedulers") and "ortools_milp" in batcher._schedulers:
            milp_sched = batcher._schedulers["ortools_milp"]
        else:
            milp_sched = batcher.active_scheduler

        try:
            profile = resolve_task_profile(t_type)
        except ValueError:
            profile = resolve_task_profile("LIGHT" if t_type in ("light", "cgpa") else "HEAVY")

        task_obj = Task(
            task_id=task_id,
            client_id=req.client_id,
            task_type=profile.task_type,
            cpu_demand_pct=profile.cpu_demand_pct,
            mem_demand_mb=profile.mem_demand_mb,
            duration_sec=profile.duration_sec,
            matrix_dim=profile.matrix_dim,
            mode="milp",
        )
        milp_res = milp_sched.assign([task_obj], workers, record_in_flight=False)
        assignments = milp_res.assignments if hasattr(milp_res, "assignments") else milp_res[0]
        assigned_worker = assignments.get(task_id, workers[0].worker_id)
        dispatch_seq = "none"
        scheduler_used = "ortools_milp"

    # 3. Capture worker in-flight count & CPU % at dispatch and record live stats
    from app.core.live_stats import live_dispatch_tracker

    live_dispatch_tracker.record_dispatch(assigned_worker)
    worker_inflight_at_dispatch = in_flight.increment(assigned_worker)
    await redis_client.incr(f"inflight:{assigned_worker}")
    await redis_client.incr(f"cluster:inflight:{assigned_worker}")

    if hasattr(cluster_state, "get_worker"):
        worker_snap = await cluster_state.get_worker(assigned_worker)
    else:
        active_list = await cluster_state.get_active_workers()
        worker_snap = next((w for w in active_list if w.worker_id == assigned_worker), None)
    worker_cpu_pct_at_dispatch = worker_snap.cpu_percent if worker_snap else 10.0

    # 4. Forward to the worker
    port_map = {"worker-1": 8001, "worker-2": 8002, "worker-3": 8003}
    worker_ip = worker_snap.ip_address if (worker_snap and worker_snap.ip_address != "virtual") else "127.0.0.1"
    worker_port = port_map.get(assigned_worker, 8001)
    worker_url = f"http://{worker_ip}:{worker_port}/execute"

    if req.payload:
        worker_payload = {
            "task_id": task_id,
            "task_type": "light" if t_type in ("light", "cgpa") else "heavy" if t_type in ("heavy", "hash", "hashing") else t_type,
            "payload": req.payload,
        }
    elif t_type in ("light", "cgpa"):
        worker_payload = {
            "task_id": task_id,
            "task_type": "light",
            "payload": {
                "courses": [{"name": "Course1", "credits": 4.0, "grade": 9.0}],
                "size": req.size,
            },
        }
    elif t_type in ("heavy", "hash", "hashing"):
        iterations = req.size if (req.size and req.size > 0) else 150000
        worker_payload = {
            "task_id": task_id,
            "task_type": "heavy",
            "payload": {
                "data": f"task-{req.client_id}-{task_id}",
                "iterations": iterations,
            },
        }
    else:
        worker_payload = {
            "task_id": task_id,
            "task_type": t_type,
            "payload": {"size": req.size or 100},
        }

    queue_ms = 0.0
    exec_ms = 0.0
    worker_status = "ok"
    result: dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            resp = await http_client.post(worker_url, json=worker_payload)
        if resp.status_code == 200:
            resp_data = resp.json()
            worker_status = "ok"
            result = resp_data.get("result", {})
            queue_ms = float(resp_data.get("queue_ms", 0.0))
            exec_ms = float(resp_data.get("execution_ms", 0.0))
        elif resp.status_code == 503:
            worker_status = "rejected_503"
            result = {"status": "rejected_503", "detail": "Worker queue full"}
        elif resp.status_code in (504, 408):
            worker_status = "timeout"
            result = {"status": "timeout", "detail": "Task wait time exceeded timeout"}
            if resp.content:
                queue_ms = float(resp.json().get("queue_ms", 0.0))
        else:
            worker_status = f"error_{resp.status_code}"
            result = {"error": resp.text}
    except httpx.TimeoutException:
        worker_status = "timeout"
        result = {"status": "timeout", "detail": "Gateway timeout contacting worker"}
    except (httpx.ConnectError, httpx.NetworkError):
        worker_status = "unavailable"
        result = {
            "status": "unavailable",
            "detail": f"Worker {assigned_worker} offline or unreachable on port {worker_port}",
        }
    except Exception as exc:
        worker_status = "error"
        result = {"error": str(exc)}
    finally:
        in_flight.decrement(assigned_worker)
        await redis_client.decr(f"inflight:{assigned_worker}")
        await redis_client.decr(f"cluster:inflight:{assigned_worker}")

    total_ms = round((time.monotonic() - start_mono) * 1000.0, 2)

    # 5. Log to CSV
    log_task_record(
        test_id=test_id,
        mode=sched_mode,
        seed=test_meta.get("seed", "none"),
        duration_s=test_meta.get("duration_s", "none"),
        lambda_per_client=test_meta.get("lambda_per_client", "none"),
        heavy_ratio=test_meta.get("heavy_ratio", "none"),
        client_id=req.client_id,
        task_id=task_id,
        task_type=t_type,
        sent_at=sent_at_val,
        scheduler_used=scheduler_used,
        dispatch_seq=dispatch_seq,
        assigned_worker=assigned_worker,
        worker_inflight_at_dispatch=worker_inflight_at_dispatch,
        worker_cpu_pct_at_dispatch=worker_cpu_pct_at_dispatch,
        queue_ms=round(queue_ms, 2),
        exec_ms=round(exec_ms, 2),
        total_ms=total_ms,
        status=worker_status,
    )

    return TaskContractResponse(
        result=result,
        assigned_worker=assigned_worker,
        queue_ms=round(queue_ms, 2),
        exec_ms=round(exec_ms, 2),
        total_ms=total_ms,
    )


@public_tasks_router.post("/tasks", response_model=TaskContractResponse)
async def public_tasks_endpoint(
    req: TaskContractRequest,
    request: Request,
) -> TaskContractResponse:
    """Public task endpoint (C1)."""
    return await execute_task_contract(req, request)


@router.post("", status_code=202)
async def submit_task(
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> Any:
    """Handle both C1 task requests and legacy profile tasks at /api/v1/tasks."""
    body = await request.json()
    task_type_str = str(body.get("task_type", "")).lower()

    # Route to C1 contract if light/heavy or if size/sent_at is present
    if task_type_str in ("light", "heavy") or "size" in body or "sent_at" in body:
        contract_req = TaskContractRequest.model_validate(body)
        return await execute_task_contract(contract_req, request)

    # Legacy 202 submission path for existing tests
    payload = TaskRequest.model_validate(body)
    batcher = _get_batcher(request)
    redis_client = _get_redis(request)
    history = _get_history(request)

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

    queue_depth = batcher.enqueue(task)
    await redis_client.setex(
        f"cluster:task:{task.task_id}",
        300,
        task.model_dump_json(),
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

