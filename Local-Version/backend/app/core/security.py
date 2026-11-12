"""API Key authentication and request security guards."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    provided_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate X-API-Key header on write endpoints.

    When `require_api_key` is False (default in local/demo browser mode) and no key is sent,
    allows the request unless an invalid non-empty key was explicitly provided.
    When `require_api_key` is True or a key is provided, constant-time verification is enforced.
    """
    if provided_key is not None and provided_key != "":
        if not secrets.compare_digest(provided_key, settings.api_key):
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

