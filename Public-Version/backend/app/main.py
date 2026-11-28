"""CloudBalance FastAPI Application Factory, Lifespan Manager, and Middleware."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, benchmark, control, health, tasks, telemetry, websocket
from app.core.config import DEFAULT_FRONTEND_DIST_DIR, ROOT_DIR, Settings, get_settings
from app.core.logger import csv_logger
from app.core.logging import configure_logging, set_correlation_id
from app.core.mongo_client import DualMongoClient
from app.core.redis_client import DualRedisClient
from app.core.security import ClientRateLimiter, verify_admin_token
from app.schedulers.base import InFlightTracker
from app.schedulers.ortools_milp import ORToolsMILPScheduler
from app.services.broadcaster import WebSocketBroadcaster
from app.services.client_stats import ClientStatsService
from app.services.cluster_state import ClusterStateService
from app.services.history import HistoryService
from app.services.scheduler_state import SchedulerStateService

FRONTEND_DIST_DIR = ROOT_DIR / DEFAULT_FRONTEND_DIST_DIR


def create_app(
    settings: Settings | None = None,
    worker_http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create and wire the CloudBalance FastAPI application."""
    cfg = settings if settings is not None else get_settings()
    configure_logging(json_logs=True)

    redis_client = DualRedisClient(
        redis_url=cfg.redis_url,
        force_memory=cfg.local_mode,
    )
    mongo_client = DualMongoClient(
        mongo_url=cfg.mongo_url,
        db_name=cfg.mongo_db_name,
        force_sqlite=cfg.local_mode,
    )
    in_flight_tracker = InFlightTracker()
    milp_scheduler = ORToolsMILPScheduler(
        time_limit_ms=cfg.solver_time_limit_ms,
        cpu_cap_pct=cfg.cpu_cap_pct,
        mem_cap_pct=cfg.mem_cap_pct,
        in_flight_tracker=in_flight_tracker,
    )
    milp_dispatch_lock = asyncio.Lock()
    cluster_state = ClusterStateService(
        redis_client=redis_client,
        in_flight_tracker=in_flight_tracker,
        ttl_seconds=cfg.worker_ttl_seconds,
        worker_urls=cfg.worker_urls,
    )
    client_stats = ClientStatsService(window_sec=10.0)
    history = HistoryService(mongo_client=mongo_client, redis_client=redis_client)
    scheduler_state = SchedulerStateService(
        cluster_state=cluster_state,
        default_scheduler=cfg.default_scheduler,
        seed_demo_workers=cfg.seed_demo_workers,
    )
    broadcaster = WebSocketBroadcaster(
        cluster_state=cluster_state,
        scheduler_state=scheduler_state,
        history=history,
        client_stats=client_stats,
        interval_sec=cfg.ws_broadcast_interval_sec,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await redis_client.connect()
        await mongo_client.connect()
        await scheduler_state.start()
        await broadcaster.start()
        try:
            yield
        finally:
            csv_logger.flush()
            contract_client = getattr(_app.state, "contract_http_client", None)
            if contract_client is not None:
                await contract_client.aclose()
            await broadcaster.stop()
            await scheduler_state.stop()
            await redis_client.close()
            await mongo_client.close()

    application = FastAPI(
        title=cfg.app_name,
        version="1.0.0",
        description="Adaptive Multi-Resource Cloud Load Balancer powered by OR-Tools MILP",
        lifespan=lifespan,
    )

    application.state.settings = cfg
    application.state.redis_client = redis_client
    application.state.mongo_client = mongo_client
    application.state.in_flight_tracker = in_flight_tracker
    application.state.milp_scheduler = milp_scheduler
    application.state.milp_dispatch_lock = milp_dispatch_lock
    application.state.rate_limiter = ClientRateLimiter(limit_per_min=cfg.rate_limit_per_min)
    application.state.cluster_state = cluster_state
    application.state.client_stats = client_stats
    application.state.history = history
    application.state.worker_http_client = worker_http_client
    application.state.scheduler_state = scheduler_state
    application.state.broadcaster = broadcaster

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def correlation_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming_cid = request.headers.get("X-Correlation-ID")
        cid = set_correlation_id(incoming_cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    application.include_router(health.router)
    application.include_router(telemetry.router)
    application.include_router(tasks.router)
    application.include_router(tasks.public_tasks_router)
    application.include_router(control.router)
    application.include_router(benchmark.router)
    application.include_router(websocket.router)
    application.include_router(admin.admin_router)
    application.include_router(admin.public_test_router)

    @application.get("/api/v1/mongo", tags=["persistence"])
    async def get_mongo_data(
        request: Request,
        _admin: str = Depends(verify_admin_token),
    ) -> dict[str, Any]:
        """Convenience direct endpoint for inspecting MongoDB collections."""
        from app.api.telemetry import inspect_mongo_state

        return await inspect_mongo_state(request, _admin=_admin)

    # Serve compiled React SPA (/, /client, /ops, /admin, /benchmark) from Controller
    # so client browsers and admins only need one unified origin.
    dist_path = Path(cfg.frontend_dist_dir)
    if not dist_path.is_absolute():
        dist_path = ROOT_DIR / dist_path
    assets_dir = dist_path / "assets"
    index_html = dist_path / "index.html"
    if assets_dir.is_dir() and index_html.is_file():
        application.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

        @application.get("/", include_in_schema=False)
        async def serve_dashboard_spa() -> FileResponse:
            return FileResponse(str(index_html))

        @application.get("/ops", include_in_schema=False)
        async def serve_ops_spa() -> FileResponse:
            return FileResponse(str(index_html))

        @application.get("/admin", include_in_schema=False)
        async def serve_admin_spa() -> FileResponse:
            return FileResponse(str(index_html))

        @application.get("/benchmark", include_in_schema=False)
        async def serve_benchmark_spa() -> FileResponse:
            return FileResponse(str(index_html))

        @application.get("/client", include_in_schema=False)
        async def serve_client_spa() -> FileResponse:
            return FileResponse(str(index_html))

    return application


app = create_app()
