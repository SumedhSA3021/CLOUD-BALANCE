"""API Key authentication and per-client_id request security guards."""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque

from fastapi import Depends, Header, HTTPException, Request, Security, WebSocket, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
worker_secret_header = APIKeyHeader(name="X-Worker-Secret", auto_error=False)


class ClientRateLimiter:
    """Sliding-window 60s rate limiter keyed by client_id (never IP)."""

    def __init__(self, limit_per_min: int = 2400, window_sec: float = 60.0) -> None:
        self.limit_per_min = max(1, int(limit_per_min))
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(self, client_id: str, *, test_active: bool = False) -> None:
        """Record one request for client_id or raise HTTP 429 if rate limit exceeded."""
        effective_limit = max(1200, self.limit_per_min) if test_active else self.limit_per_min
        now = time.monotonic()
        cutoff = now - self.window_sec
        with self._lock:
            bucket = self._hits.get(client_id)
            if bucket is None:
                bucket = deque()
                self._hits[client_id] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= effective_limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for client_id '{client_id}' ({effective_limit}/min)",
                )
            bucket.append(now)
            if len(self._hits) > 1024:
                stale = [cid for cid, dq in self._hits.items() if not dq or dq[-1] <= cutoff]
                for cid in stale:
                    self._hits.pop(cid, None)


async def verify_api_key(
    provided_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate X-API-Key header on write endpoints.

    When `require_api_key` is False (default in local/demo browser mode) and no key is sent,
    allows the request unless an invalid non-empty key was explicitly provided.
    When `require_api_key` is True or a key is provided, constant-time verification is enforced.
    """
    expected_key = (settings.api_key or "").strip()
    if provided_key is not None and provided_key != "":
        if not expected_key or not secrets.compare_digest(provided_key, expected_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        return provided_key

    if settings.require_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    return "anonymous-allowed"


def resolve_app_settings(request_or_ws: Request | WebSocket) -> Settings:
    """Resolve app-scoped Settings first so tests overriding create_app(settings=...) stay isolated."""
    app_state = getattr(getattr(request_or_ws, "app", None), "state", None)
    cfg = getattr(app_state, "settings", None)
    return cfg if isinstance(cfg, Settings) else get_settings()


async def verify_request_api_key(
    request: Request,
    provided_key: str | None = Security(api_key_header),
) -> str:
    """Validate X-API-Key against app-scoped Settings first, falling back to global Settings."""
    return await verify_api_key(provided_key=provided_key, settings=resolve_app_settings(request))


async def verify_admin_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """Validate Bearer token against configured ADMIN_TOKEN using constant-time comparison."""
    expected = resolve_app_settings(request).admin_token
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not secrets.compare_digest(parts[1], expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin bearer token",
        )
    return parts[1]


def verify_admin_ws_token(websocket: WebSocket) -> str | None:
    """Validate admin token on WebSocket handshake via Bearer header or ?token= query param."""
    expected = resolve_app_settings(websocket).admin_token
    candidate = websocket.query_params.get("token", "").strip()
    if not candidate:
        auth_header = websocket.headers.get("authorization", "")
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1].strip()
    if not candidate or not secrets.compare_digest(candidate, expected):
        return None
    return candidate


async def verify_worker_secret(
    request: Request,
    provided_secret: str | None = Security(worker_secret_header),
    authorization: str | None = Header(default=None),
) -> str:
    """Validate worker telemetry requests against WORKER_SECRET (X-Worker-Secret or Bearer)."""
    expected = resolve_app_settings(request).worker_secret
    candidate = (provided_secret or "").strip()
    if not candidate and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1].strip()
    if not candidate or not secrets.compare_digest(candidate, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing worker secret",
        )
    return candidate

