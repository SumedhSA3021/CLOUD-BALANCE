"""WebSocket Broadcaster streaming CLUSTER_SNAPSHOT every 1.5s to dashboards."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from fastapi import WebSocket

from app.core.logging import get_logger
from app.models.schemas import ClusterSnapshot
from app.services.batcher import MicroBatcherService
from app.services.client_stats import ClientStatsService
from app.services.cluster_state import ClusterStateService
from app.services.history import HistoryService

logger = get_logger("service.broadcaster")


class WebSocketBroadcaster:
    """Manages active WebSocket connections and broadcasts CLUSTER_SNAPSHOT periodically."""

    def __init__(
        self,
        cluster_state: ClusterStateService,
        batcher: MicroBatcherService,
        history: HistoryService,
        client_stats: ClientStatsService,
        interval_sec: float = 1.5,
    ) -> None:
        self._cluster_state = cluster_state
        self._batcher = batcher
        self._history = history
        self._client_stats = client_stats
        self._interval_sec = interval_sec
        self._connections: set[WebSocket] = set()
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and immediately send an initial snapshot."""
        await websocket.accept()
        self._connections.add(websocket)
        snapshot = await self.build_snapshot()
        await websocket.send_json(snapshot.model_dump(mode="json"))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a closed WebSocket connection."""
        self._connections.discard(websocket)

    async def build_snapshot(self) -> ClusterSnapshot:
        """Assemble a complete live ClusterSnapshot for the dashboard."""
        worker_items = await self._cluster_state.get_worker_snapshots()
        recent_assignments = self._history.get_recent_assignments(limit=20)
        clients = self._client_stats.get_client_stats()
        measured_lambda = self._client_stats.get_lambda_total()
        effective_lambda = (
            measured_lambda if measured_lambda > 0.0 else self._batcher.configured_lambda
        )

        return ClusterSnapshot(
            type="CLUSTER_SNAPSHOT",
            timestamp=datetime.now(UTC),
            workers=worker_items,
            recent_assignments=recent_assignments,
            clients=clients,
            queue_depth=self._batcher.queue_depth,
            active_scheduler=self._batcher.active_scheduler_name,
            lambda_total=effective_lambda,
            avg_solver_latency_ms=self._history.get_avg_solver_latency_ms(),
            degraded_mode=self._history.degraded_mode,
            degraded_warning=self._history.degraded_warning,
            paused=self._batcher.paused,
        )

    async def broadcast_now(self) -> ClusterSnapshot:
        """Build and broadcast a snapshot immediately to all connected clients."""
        snapshot = await self.build_snapshot()
        if not self._connections:
            return snapshot

        payload = snapshot.model_dump(mode="json")
        dead_sockets: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead_sockets.append(ws)
        for ws in dead_sockets:
            self._connections.discard(ws)
        return snapshot

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval_sec)
                if self._connections:
                    await self.broadcast_now()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ws_broadcast_loop_error", error=str(exc))

    async def start(self) -> None:
        """Start periodic 1.5s WebSocket broadcast task."""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop periodic broadcast task."""
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None

