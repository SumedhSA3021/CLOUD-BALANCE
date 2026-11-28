"""WebSocket Endpoint streaming live CLUSTER_SNAPSHOT every 1.5s."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.broadcaster import WebSocketBroadcaster

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Stream real-time ClusterSnapshot updates to connected dashboards."""
    broadcaster: WebSocketBroadcaster = websocket.app.state.broadcaster
    await broadcaster.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "PONG"})
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception:
        broadcaster.disconnect(websocket)

