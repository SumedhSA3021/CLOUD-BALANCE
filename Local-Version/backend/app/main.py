"""CloudBalance FastAPI Application Factory, Lifespan Manager, and Middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import benchmark, control, health, tasks, telemetry, websocket
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, set_correlation_id
from app.core.mongo_client import DualMongoClient
from app.core.redis_client import DualRedisClient
from app.schedulers.base import InFlightTracker
from app.services.batcher import MicroBatcherService
from app.services.broadcaster import WebSocketBroadcaster
from app.services.client_stats import ClientStatsService
from app.services.cluster_state import ClusterStateService
from app.services.dispatcher import DispatcherService
from app.services.history import HistoryService

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


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
    cluster_state = ClusterStateService(
        redis_client=redis_client,
        in_flight_tracker=in_flight_tracker,
        ttl_seconds=cfg.worker_ttl_seconds,
    )
    client_stats = ClientStatsService(window_sec=10.0)
    history = HistoryService(mongo_client=mongo_client, redis_client=redis_client)
    dispatcher = DispatcherService(
        cluster_state=cluster_state,
        history=history,
        timeout_sec=cfg.dispatch_timeout_sec,
        max_retries=cfg.dispatch_max_retries,
        http_client=worker_http_client,
    )
    batcher = MicroBatcherService(
        cluster_state=cluster_state,
        dispatcher=dispatcher,
        history=history,
        client_stats=client_stats,
        in_flight_tracker=in_flight_tracker,
        max_queue_depth=cfg.max_queue_depth,
        rate_limit_per_sec=cfg.rate_limit_per_sec,
        batch_window_ms=cfg.batch_window_ms,
        batch_max_size=cfg.batch_max_size,
        solver_time_limit_ms=cfg.solver_time_limit_ms,
        cpu_cap_pct=cfg.cpu_cap_pct,
        mem_cap_pct=cfg.mem_cap_pct,
        default_scheduler=cfg.default_scheduler,
        seed_demo_workers=cfg.seed_demo_workers,
    )
    broadcaster = WebSocketBroadcaster(
        cluster_state=cluster_state,
        batcher=batcher,
        history=history,
        client_stats=client_stats,
        interval_sec=cfg.ws_broadcast_interval_sec,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await redis_client.connect()
        await mongo_client.connect()
        await batcher.start()
        await broadcaster.start()
        try:
            yield
        finally:
            await broadcaster.stop()
            await batcher.stop()
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
    application.state.cluster_state = cluster_state
    application.state.client_stats = client_stats
    application.state.history = history
    application.state.dispatcher = dispatcher
    application.state.batcher = batcher
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
    application.include_router(control.router)
    application.include_router(benchmark.router)
    application.include_router(websocket.router)

    @application.get("/api/v1/mongo", tags=["persistence"])
    async def get_mongo_data(request: Request) -> dict[str, Any]:
        """Convenience direct endpoint for inspecting MongoDB collections."""
        from app.api.telemetry import inspect_mongo_state
        return await inspect_mongo_state(request)

    # Serve compiled React SPA (/ and /client) directly from Controller (:8000)
    # so 3+ client laptops only need ONE single public URL (http://<CONTROLLER_IP>:8000).
    assets_dir = FRONTEND_DIST_DIR / "assets"
    index_html = FRONTEND_DIST_DIR / "index.html"
    if assets_dir.is_dir() and index_html.is_file():
        application.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

        @application.get("/", include_in_schema=False)
        async def serve_dashboard_spa() -> FileResponse:
            return FileResponse(str(index_html))

        @application.get("/client", include_in_schema=False)
        async def serve_client_spa() -> FileResponse:
            return FileResponse(str(index_html))

    return application


app = create_app()

