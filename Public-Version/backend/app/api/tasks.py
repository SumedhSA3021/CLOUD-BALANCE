"""Unified Task Execution Endpoints (`POST /tasks`, alias `POST /api/v1/tasks`)."""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import (
    DEFAULT_DISPATCH_TIMEOUT_SEC,
    DEFAULT_WORKER_URLS,
    WorkerEndpoint,
    parse_worker_endpoints,
)
from app.core.logger import log_task_record
from app.core.logging import get_logger
from app.core.profiles import resolve_task_profile
from app.core.redis_client import DualRedisClient
from app.core.security import verify_request_api_key
from app.models.schemas import Assignment, Task, Telemetry
from app.schedulers.test_hooks import get_current_test_id, get_current_test_metadata, is_test_running

WORKERS = [ep.worker_id for ep in parse_worker_endpoints(DEFAULT_WORKER_URLS)]

logger = get_logger("api.tasks")
router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
public_tasks_router = APIRouter(tags=["tasks"])


class TaskContractRequest(BaseModel):
    """Shared contract task request supporting optional client_rate and client_task_type metadata."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    client_id: str = Field(..., min_length=1, max_length=64)
    task_type: str = Field(default="light", description="'light' or 'heavy'")
    size: int | None = Field(default=None, ge=1, le=3_000_000, description="Optional payload size or iterations")
    sent_at: float | str | None = Field(default=None, description="Client departure timestamp")
    payload: dict[str, Any] | None = Field(default=None, description="Optional custom task payload")
    client_rate: float | None = Field(
        default=None,
        ge=0.5,
        le=10.0,
        description="Optional client-declared Poisson rate (req/s)",
    )
    client_task_type: Literal["light", "heavy"] | None = Field(
        default=None,
        description="Optional client-declared task type ('light' or 'heavy')",
    )

    @field_validator("client_id", mode="before")
    @classmethod
    def validate_client_id(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("client_id must be a non-empty string")
        return value.strip()

    @field_validator("task_type", mode="before")
    @classmethod
    def validate_task_type(cls, value: Any) -> str:
        cleaned = str(value or "light").strip()
        try:
            resolve_task_profile(cleaned)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return cleaned

    @field_validator("sent_at", mode="before")
    @classmethod
    def sanitize_sent_at(cls, value: Any) -> float | str | None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("sent_at must be a finite number")
        return value

    @field_validator("client_rate", mode="before")
    @classmethod
    def validate_client_rate(cls, value: Any) -> float | None:
        """Accept omitted rate or finite float in [0.5, 10.0]; reject booleans."""
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("client_rate must be a finite number between 0.5 and 10")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("client_rate must be a finite number")
        return value

    @field_validator("client_task_type", mode="before")
    @classmethod
    def validate_client_task_type(cls, value: Any) -> str | None:
        """Accept omitted type or 'light'/'heavy'."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("client_task_type must be 'light' or 'heavy'")
        cleaned = value.strip().lower()
        if cleaned not in ("light", "heavy"):
            raise ValueError("client_task_type must be 'light' or 'heavy'")
        return cleaned


class TaskContractResponse(BaseModel):
    """Shared contract task response mapping worker execution_ms -> exec_ms and scheduler_used."""

    model_config = ConfigDict(extra="ignore")

    result: dict[str, Any] = Field(default_factory=dict)
    assigned_worker: str
    queue_ms: float
    exec_ms: float
    total_ms: float
    dispatch_seq: int | str | None = Field(default=None)
    scheduler_used: str | None = Field(default=None)


def _get_app_state(request: Any) -> Any:
    app = getattr(request, "app", request)
    return getattr(app, "state", app)


def _get_scheduler_state(request: Request) -> Any:
    return getattr(_get_app_state(request), "scheduler_state", None)


def _get_redis(request: Request) -> DualRedisClient:
    return cast(DualRedisClient, getattr(_get_app_state(request), "redis_client", None))


async def _resolve_arrival_mode(
    app_state: Any,
    redis_client: DualRedisClient,
    scheduler_state: Any,
) -> str:
    """Resolve scheduler mode ONCE at task arrival ('round_robin' or 'milp')."""
    test_meta = get_current_test_metadata()
    if test_meta and "mode" in test_meta:
        raw = str(test_meta["mode"]).lower().strip()
    else:
        stored_mode = await redis_client.get("sched_mode")
        if stored_mode:
            raw = stored_mode.lower().strip()
        else:
            raw = str(getattr(scheduler_state, "active_scheduler_name", "ortools_milp")).lower().strip()
    return "round_robin" if "round_robin" in raw else "milp"


def _get_worker_endpoints(app_state: Any) -> list[WorkerEndpoint]:
    """Resolve ordered worker endpoints from configured WORKER_URLS."""
    app_settings = getattr(app_state, "settings", None)
    configured = getattr(app_settings, "worker_urls", None)
    endpoints = parse_worker_endpoints(configured)
    return endpoints or parse_worker_endpoints(DEFAULT_WORKER_URLS)


def _build_worker_execute_url(
    worker_id: str,
    worker_snap: Telemetry | None,
    endpoint_map: dict[str, WorkerEndpoint],
    endpoints: list[WorkerEndpoint],
) -> str:
    """Resolve worker `/execute` URL from WORKER_URLS and live telemetry."""
    ep = endpoint_map.get(worker_id)
    custom_urls = [item.url for item in endpoints] != DEFAULT_WORKER_URLS
    if worker_snap is not None and worker_snap.ip_address != "virtual":
        if ep is not None and custom_urls:
            return f"{ep.url}/execute"
        scheme = ep.scheme if ep is not None else "http"
        return f"{scheme}://{worker_snap.ip_address}:{worker_snap.port}/execute"
    if ep is not None:
        return f"{ep.url}/execute"
    if endpoints:
        return f"{endpoints[0].url}/execute"
    return f"{DEFAULT_WORKER_URLS[0]}/execute"


def _get_milp_scheduler(app_state: Any, in_flight: Any) -> Any:
    """Return dedicated ORToolsMILPScheduler instance."""
    sched = getattr(app_state, "milp_scheduler", None)
    if sched is not None:
        return sched
    from app.schedulers.ortools_milp import ORToolsMILPScheduler

    sched = ORToolsMILPScheduler(in_flight_tracker=in_flight)
    app_state.milp_scheduler = sched
    return sched


def _get_milp_dispatch_lock(app_state: Any) -> asyncio.Lock:
    """Return asyncio.Lock guarding atomic read-solve-increment in MILP dispatch."""
    lock = getattr(app_state, "milp_dispatch_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app_state.milp_dispatch_lock = lock
    return cast(asyncio.Lock, lock)


async def _enforce_max_payload_size(request: Request) -> None:
    """Reject oversized HTTP request payloads on POST /tasks before parsing."""
    app_state = _get_app_state(request)
    app_settings = getattr(app_state, "settings", None)
    max_bytes = int(getattr(app_settings, "max_payload_bytes", 65536))
    headers = getattr(request, "headers", None)
    if headers is not None and "content-length" in headers:
        try:
            content_len = int(headers["content-length"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
        if content_len > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Payload size ({content_len} bytes) exceeds limit of {max_bytes} bytes",
            )
    if hasattr(request, "body"):
        raw_body = await request.body()
        if len(raw_body) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Payload size ({len(raw_body)} bytes) exceeds limit of {max_bytes} bytes",
            )


async def execute_task_contract(
    req: TaskContractRequest,
    request: Request,
) -> TaskContractResponse:
    """Execute C1 task contract: schedule, forward to worker, log to CSV, and return timings."""
    start_mono = time.monotonic()
    now_wall = round(time.time(), 3)
    sent_at_val = req.sent_at if req.sent_at is not None else now_wall

    app_state = _get_app_state(request)
    scheduler_state = _get_scheduler_state(request)
    redis_client = _get_redis(request)
    cluster_state: Any = getattr(app_state, "cluster_state", None)
    in_flight: Any = getattr(app_state, "in_flight_tracker", None)
    if cluster_state is None or in_flight is None:
        raise HTTPException(status_code=503, detail="Controller state unavailable")

    app_settings = getattr(app_state, "settings", None)
    max_bytes = int(getattr(app_settings, "max_payload_bytes", 65536))
    if len(req.model_dump_json().encode("utf-8")) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Task payload exceeds limit of {max_bytes} bytes",
        )

    from app.api.admin import TestState, test_manager

    if test_manager.state == TestState.DRAINING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Test is draining in-flight tasks; new tasks rejected until idle",
        )

    rate_limiter: Any = getattr(app_state, "rate_limiter", None)
    if rate_limiter is not None:
        rate_limiter.check_and_record(req.client_id, test_active=is_test_running())

    task_id = f"tsk-{uuid.uuid4().hex[:10]}"
    t_type = (req.task_type or "light").lower().strip()

    try:
        profile = resolve_task_profile(t_type)
    except ValueError:
        profile = resolve_task_profile("LIGHT" if t_type in ("light", "cgpa") else "HEAVY")

    # 1. Read mode ONCE at arrival and freeze onto task.mode
    if test_manager.state == TestState.ARMED:
        test_meta: dict[str, Any] = {}
        test_id = "none"
    else:
        test_meta = get_current_test_metadata()
        test_id = get_current_test_id()
    arrival_mode = await _resolve_arrival_mode(app_state, redis_client, scheduler_state)
    task = Task(
        task_id=task_id,
        client_id=req.client_id,
        task_type=profile.task_type,
        cpu_demand_pct=profile.cpu_demand_pct,
        mem_demand_mb=profile.mem_demand_mb,
        duration_sec=profile.duration_sec,
        matrix_dim=profile.matrix_dim,
        mode=arrival_mode,
    )

    from app.core.live_stats import live_dispatch_tracker

    endpoints = _get_worker_endpoints(app_state)
    worker_ids = [ep.worker_id for ep in endpoints]
    endpoint_map = {ep.worker_id: ep for ep in endpoints}

    solver_latency_ms = 0.0
    workers_cache: list[Telemetry] = []

    # 2. Dispatch strictly by task.mode; log scheduler_used & dispatch_seq at decision time
    if task.mode == "round_robin":
        n = await redis_client.incr("rr_counter")
        assigned_worker = worker_ids[(n - 1) % len(worker_ids)]
        dispatch_seq: int | str = n
        scheduler_used = "round_robin"
        worker_inflight_at_dispatch = in_flight.increment(assigned_worker)
        live_dispatch_tracker.record_dispatch(assigned_worker)
    else:
        workers_cache = await cluster_state.get_active_workers()
        if not workers_cache:
            workers_cache = [
                Telemetry(
                    worker_id=ep.worker_id,
                    ip_address=ep.host,
                    port=ep.port,
                    cpu_percent=10.0,
                    memory_total_mb=4096.0,
                    memory_used_mb=512.0,
                    memory_percent=12.5,
                    load_avg_1m=0.5,
                    active_task_count=0,
                )
                for ep in endpoints
            ]
        milp_sched = _get_milp_scheduler(app_state, in_flight)
        milp_lock = _get_milp_dispatch_lock(app_state)
        async with milp_lock:
            milp_res = milp_sched.assign([task], workers_cache, record_in_flight=False)
            assignments = getattr(milp_res, "assignments", None)
            if assignments is None:
                assignments = cast(Any, milp_res)[0]
            assigned_worker = assignments.get(task.task_id, workers_cache[0].worker_id)
            worker_inflight_at_dispatch = in_flight.increment(assigned_worker)
            live_dispatch_tracker.record_dispatch(assigned_worker)
            res_meta = getattr(milp_res, "meta", None)
            solver_latency_ms = float(getattr(res_meta, "solver_latency_ms", 0.0))
        dispatch_seq = "none"
        scheduler_used = "ortools_milp"

    logger.info(
        "task_dispatch_decision",
        task_id=task.task_id,
        client_id=task.client_id,
        mode=task.mode,
        scheduler_used=scheduler_used,
        dispatch_seq=dispatch_seq,
        assigned_worker=assigned_worker,
        worker_inflight_at_dispatch=worker_inflight_at_dispatch,
    )

    queue_ms = 0.0
    exec_ms = 0.0
    worker_status = "ok"
    failover = False
    result: dict[str, Any] = {}
    first_ep = endpoints[0]
    worker_ip = first_ep.host
    worker_port = first_ep.port
    worker_snap = None
    allow_virtual = getattr(getattr(app_state, "settings", None), "seed_demo_workers", True)
    worker_cpu_pct_at_dispatch = 10.0

    # 3. Guarantee in-flight counter decrements even on setup/dispatch error
    try:
        await redis_client.incr(f"inflight:{assigned_worker}")
        await redis_client.incr(f"cluster:inflight:{assigned_worker}")
        client_stats: Any = getattr(app_state, "client_stats", None)
        if client_stats is not None:
            client_stats.record_enqueue(req.client_id, start_mono)

        worker_snap = next((w for w in workers_cache if w.worker_id == assigned_worker), None)
        if worker_snap is None:
            if hasattr(cluster_state, "get_worker"):
                worker_snap = await cluster_state.get_worker(assigned_worker)
            else:
                active_list = await cluster_state.get_active_workers()
                worker_snap = next((w for w in active_list if w.worker_id == assigned_worker), None)

        if not worker_snap and allow_virtual:
            await cluster_state.seed_virtual_workers_if_empty()
            if hasattr(cluster_state, "get_worker"):
                worker_snap = await cluster_state.get_worker(assigned_worker)
            else:
                active_list = await cluster_state.get_active_workers()
                worker_snap = next((w for w in active_list if w.worker_id == assigned_worker), None)
        worker_cpu_pct_at_dispatch = worker_snap.cpu_percent if worker_snap else 10.0
        if test_id != "none" and test_manager.state == TestState.RUNNING:
            test_manager.register_inflight_task(
                task_id,
                {
                    "start_mono": start_mono,
                    "test_id": test_id,
                    "mode": task.mode,
                    "seed": test_meta.get("seed", "none"),
                    "duration_s": test_meta.get("duration_s", "none"),
                    "lambda_per_client": test_meta.get("lambda_per_client", "none"),
                    "heavy_ratio": test_meta.get("heavy_ratio", "none"),
                    "client_id": req.client_id,
                    "task_type": t_type,
                    "sent_at": sent_at_val,
                    "scheduler_used": scheduler_used,
                    "dispatch_seq": dispatch_seq,
                    "assigned_worker": assigned_worker,
                    "worker_inflight_at_dispatch": worker_inflight_at_dispatch,
                    "worker_cpu_pct_at_dispatch": worker_cpu_pct_at_dispatch,
                    "failover": False,
                    "client_rate": req.client_rate,
                    "client_task_type": req.client_task_type,
                },
            )

        # 4. Forward to the worker or execute in-process if standalone/virtual
        assigned_ep = endpoint_map.get(assigned_worker, first_ep)
        default_ip = "virtual" if allow_virtual else assigned_ep.host
        worker_ip = worker_snap.ip_address if worker_snap else default_ip
        worker_port = worker_snap.port if worker_snap else assigned_ep.port

        if req.payload is not None:
            normalized_type = (
                "light"
                if t_type in ("light", "cgpa")
                else "heavy"
                if t_type in ("heavy", "hash", "hashing")
                else t_type
            )
            worker_payload: dict[str, Any] = {
                "task_id": task_id,
                "task_type": normalized_type,
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
                "cpu_demand_pct": profile.cpu_demand_pct,
                "mem_demand_mb": profile.mem_demand_mb,
                "matrix_dim": profile.matrix_dim,
                "duration_sec": profile.duration_sec,
                "payload": {"size": req.size or 100},
            }

        def _execute_local_workload() -> tuple[str, dict[str, Any], float, float]:
            """Execute light/heavy worker functions in-process with real computation and timing."""
            t_start = time.perf_counter()
            raw_payload = worker_payload.get("payload")
            payload_data: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
            if t_type in ("light", "cgpa"):
                from worker.executor import _calculate_cgpa
                res = _calculate_cgpa(payload_data)
            elif t_type in ("heavy", "hash", "hashing"):
                from worker.executor import _run_heavy_hashing_loop
                raw_iter = payload_data.get("iterations", 150000)
                try:
                    iter_cnt = min(500000, int(raw_iter))
                except (ValueError, TypeError) as exc:
                    raise HTTPException(status_code=400, detail="Iterations must be an integer") from exc
                if iter_cnt <= 0:
                    raise HTTPException(status_code=400, detail="Iterations must be positive")
                payload_data["iterations"] = iter_cnt
                res = _run_heavy_hashing_loop(payload_data, default_iterations=iter_cnt)
            else:
                res = {"status": "ok", "task_id": task_id}
            elapsed = round((time.perf_counter() - t_start) * 1000.0, 2)
            return "ok", res, 0.5, elapsed

        if worker_ip == "virtual":
            worker_status, result, queue_ms, exec_ms = await asyncio.to_thread(_execute_local_workload)
        else:
            dispatch_timeout = float(
                getattr(
                    getattr(app_state, "settings", None),
                    "dispatch_timeout_sec",
                    DEFAULT_DISPATCH_TIMEOUT_SEC,
                )
            )

            async def _dispatch_http(target_url: str) -> tuple[str, dict[str, Any], float, float]:
                ext_client = getattr(app_state, "worker_http_client", None)
                if ext_client is not None:
                    resp = await ext_client.post(target_url, json=worker_payload)
                else:
                    async with httpx.AsyncClient(timeout=dispatch_timeout) as http_client:
                        resp = await http_client.post(target_url, json=worker_payload)
                if resp.status_code == 200:
                    resp_data = resp.json()
                    q_ms = float(resp_data.get("queue_ms", 0.0))
                    e_ms = float(resp_data.get("execution_ms", 0.0))
                    return (
                        "ok",
                        resp_data.get("result", {}),
                        q_ms if math.isfinite(q_ms) and q_ms >= 0.0 else 0.0,
                        e_ms if math.isfinite(e_ms) and e_ms >= 0.0 else 0.0,
                    )
                if resp.status_code in (400, 413, 422):
                    detail_msg = resp.text
                    try:
                        detail_msg = resp.json().get("detail", detail_msg)
                    except Exception:
                        pass
                    raise HTTPException(status_code=resp.status_code, detail=str(detail_msg))
                if resp.status_code == 503:
                    return "rejected_503", {"status": "rejected_503", "detail": "Worker queue full"}, 0.0, 0.0
                if resp.status_code in (504, 408):
                    q_ms = 0.0
                    if resp.content:
                        try:
                            q_ms = float(resp.json().get("queue_ms", 0.0))
                        except Exception:
                            pass
                    return (
                        "timeout",
                        {"status": "timeout", "detail": "Task wait time exceeded timeout"},
                        q_ms if math.isfinite(q_ms) and q_ms >= 0.0 else 0.0,
                        0.0,
                    )
                return f"error_{resp.status_code}", {"error": resp.text}, 0.0, 0.0

            worker_url = _build_worker_execute_url(assigned_worker, worker_snap, endpoint_map, endpoints)
            try:
                worker_status, result, queue_ms, exec_ms = await _dispatch_http(worker_url)
            except HTTPException:
                raise
            except (httpx.ConnectError, httpx.NetworkError):
                if allow_virtual:
                    worker_status, result, queue_ms, exec_ms = await asyncio.to_thread(_execute_local_workload)
                else:
                    if hasattr(cluster_state, "evict_worker"):
                        await cluster_state.evict_worker(assigned_worker)
                    live_workers = workers_cache or await cluster_state.get_active_workers()
                    killed_set = getattr(cluster_state, "killed_workers", set())
                    remaining = [
                        w
                        for w in live_workers
                        if w.worker_id != assigned_worker and w.worker_id not in killed_set
                    ]
                    if remaining:
                        if task.mode == "round_robin":
                            by_id = {w.worker_id: w for w in remaining}
                            start_i = worker_ids.index(assigned_worker) if assigned_worker in worker_ids else 0
                            rr_order = [
                                worker_ids[(start_i + offset) % len(worker_ids)]
                                for offset in range(1, len(worker_ids))
                            ]
                            fallback_w = next((by_id[wid] for wid in rr_order if wid in by_id), remaining[0])
                        else:
                            fallback_w = min(
                                remaining,
                                key=lambda w: (w.cpu_percent + in_flight.get_count(w.worker_id) * 15.0, w.worker_id),
                            )
                        failover = True
                        in_flight.decrement(assigned_worker)
                        await redis_client.decr(f"inflight:{assigned_worker}")
                        await redis_client.decr(f"cluster:inflight:{assigned_worker}")
                        assigned_worker = fallback_w.worker_id
                        worker_inflight_at_dispatch = in_flight.increment(assigned_worker)
                        await redis_client.incr(f"inflight:{assigned_worker}")
                        await redis_client.incr(f"cluster:inflight:{assigned_worker}")
                        live_dispatch_tracker.record_dispatch(assigned_worker)
                        worker_cpu_pct_at_dispatch = fallback_w.cpu_percent
                        test_manager.update_inflight_worker(
                            task_id,
                            assigned_worker,
                            worker_inflight_at_dispatch,
                            worker_cpu_pct_at_dispatch,
                            failover=True,
                        )
                        fallback_url = _build_worker_execute_url(
                            assigned_worker, fallback_w, endpoint_map, endpoints
                        )
                        try:
                            worker_status, result, queue_ms, exec_ms = await _dispatch_http(fallback_url)
                        except (httpx.ConnectError, httpx.NetworkError):
                            worker_status = "unavailable"
                            result = {
                                "status": "unavailable",
                                "detail": f"Worker {assigned_worker} offline or unreachable",
                            }
                        except httpx.TimeoutException:
                            worker_status = "timeout"
                            result = {"status": "timeout", "detail": "Gateway timeout contacting worker"}
                    else:
                        worker_status = "unavailable"
                        result = {
                            "status": "unavailable",
                            "detail": f"Worker {assigned_worker} offline or unreachable on port {worker_port}",
                        }
            except httpx.TimeoutException:
                worker_status = "timeout"
                result = {"status": "timeout", "detail": "Gateway timeout contacting worker"}
            except Exception as exc:
                worker_status = "error"
                result = {"error": str(exc)}
    finally:
        in_flight.decrement(assigned_worker)
        await redis_client.decr(f"inflight:{assigned_worker}")
        await redis_client.decr(f"cluster:inflight:{assigned_worker}")

    if worker_ip == "virtual" and worker_snap and hasattr(cluster_state, "update_telemetry"):
        delta_cpu = 15.0 if t_type in ("heavy", "hash", "hashing") else 3.0
        new_cpu = min(96.0, round(worker_snap.cpu_percent + delta_cpu, 1))
        busy_telemetry = worker_snap.model_copy(
            update={
                "cpu_percent": new_cpu,
                "active_task_count": max(0, in_flight.get_count(assigned_worker)),
            }
        )
        asyncio.create_task(cluster_state.update_telemetry(busy_telemetry))

    total_ms = round((time.monotonic() - start_mono) * 1000.0, 2)

    # 5. Log to CSV (skip if draining deadline already recorded status='timeout' for this leftover)
    should_log = (test_id == "none") or test_manager.complete_inflight_task(task_id)
    if should_log:
        log_task_record(
            test_id=test_id,
            mode=task.mode,
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
            failover=failover,
            client_rate=req.client_rate,
            client_task_type=req.client_task_type,
        )

        if test_id != "none" and not str(req.client_id).startswith("sim-"):
            test_manager.record_task_result(worker_status)

    if client_stats is not None:
        client_stats.record_assigned(req.client_id, assigned_worker, queue_wait_ms=round(queue_ms, 2))

    history: Any = getattr(app_state, "history", None)
    if history is not None:
        assignment = Assignment(
            task_id=task_id,
            client_id=req.client_id,
            task_type=profile.task_type,
            cpu_demand_pct=profile.cpu_demand_pct,
            mem_demand_mb=profile.mem_demand_mb,
            assigned_worker_id=assigned_worker,
            scheduler=scheduler_used,
            scheduler_used=scheduler_used,
            dispatch_seq=dispatch_seq if isinstance(dispatch_seq, int) else None,
            worker_inflight_at_dispatch=worker_inflight_at_dispatch,
            solver_latency_ms=solver_latency_ms,
            queue_wait_ms=round(queue_ms, 2),
            execution_ms=round(exec_ms, 2),
            status="COMPLETED" if worker_status == "ok" else "FAILED",
            degraded=False,
            timestamp=datetime.now(UTC),
        )
        await history.record_assignment(assignment)

    return TaskContractResponse(
        result=result,
        assigned_worker=assigned_worker,
        queue_ms=round(queue_ms, 2),
        exec_ms=round(exec_ms, 2),
        total_ms=total_ms,
        dispatch_seq=dispatch_seq,
        scheduler_used=scheduler_used,
    )


@public_tasks_router.post(
    "/tasks",
    response_model=TaskContractResponse,
    dependencies=[Depends(_enforce_max_payload_size)],
)
async def public_tasks_endpoint(
    req: TaskContractRequest,
    request: Request,
) -> TaskContractResponse:
    """Public task endpoint (C1)."""
    return await execute_task_contract(req, request)


@router.post("", response_model=TaskContractResponse, dependencies=[Depends(_enforce_max_payload_size)])
async def submit_task_alias(
    req: TaskContractRequest,
    request: Request,
    _api_key: str = Depends(verify_request_api_key),
) -> TaskContractResponse:
    """Thin alias delegating `/api/v1/tasks` requests directly into `execute_task_contract`."""
    return await execute_task_contract(req, request)

