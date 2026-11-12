"""Dual-mode Async Redis Client with In-Memory TTL Cache Fallback."""

from __future__ import annotations

import asyncio
import fnmatch
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.logging import get_logger

logger = get_logger("redis_client")


class InMemoryTTLStore:
    """Async-safe in-memory key-value store with strict per-key TTL expiration."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def _purge_expired_sync(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)

    async def setex(self, name: str, time_sec: int, value: str) -> bool:
        """Set key `name` to hold string `value` and expire after `time_sec` seconds."""
        expires_at = time.monotonic() + float(time_sec)
        async with self._lock:
            self._data[name] = (value, expires_at)
        return True

    async def get(self, name: str) -> str | None:
        """Get the value of key `name`, or None if expired/missing."""
        now = time.monotonic()
        async with self._lock:
            entry = self._data.get(name)
            if entry is None:
                return None
            val, expires_at = entry
            if expires_at <= now:
                self._data.pop(name, None)
                return None
            return val

    async def delete(self, *names: str) -> int:
        """Delete one or more keys and return count deleted."""
        removed = 0
        async with self._lock:
            for name in names:
                if self._data.pop(name, None) is not None:
                    removed += 1
        return removed

    async def keys(self, pattern: str = "*") -> list[str]:
        """Return all non-expired keys matching `pattern`."""
        now = time.monotonic()
        async with self._lock:
            self._purge_expired_sync(now)
            return sorted(k for k in self._data if fnmatch.fnmatchcase(k, pattern))

    async def ttl(self, name: str) -> int:
        """Return remaining TTL in seconds, -2 if missing/expired."""
        now = time.monotonic()
        async with self._lock:
            entry = self._data.get(name)
            if entry is None:
                return -2
            _, expires_at = entry
            remaining = expires_at - now
            if remaining <= 0:
                self._data.pop(name, None)
                return -2
            return max(1, int(round(remaining)))

    async def ping(self) -> bool:
        """Health check ping."""
        return True

    async def flushdb(self) -> None:
        """Clear all keys."""
        async with self._lock:
            self._data.clear()

    async def close(self) -> None:
        """No-op close for interface compatibility."""
        return None


class DualRedisClient:
    """Unified Redis client that uses real Redis when reachable or InMemoryTTLStore in local mode."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", force_memory: bool = False) -> None:
        self._redis_url = redis_url
        self._force_memory = force_memory
        self._memory_store = InMemoryTTLStore()
        self._redis: Any = None
        self._using_memory: bool = True

    @property
    def backend_mode(self) -> str:
        """Return 'in_memory_ttl' or 'redis'."""
        return "in_memory_ttl" if self._using_memory else "redis"

    async def connect(self) -> None:
        """Attempt connection to real Redis unless forced to in-memory mode."""
        if self._force_memory:
            self._using_memory = True
            logger.info("redis_client_initialized", mode="in_memory_ttl")
            return

        try:
            client: Any = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
            )
            await client.ping()
            self._redis = client
            self._using_memory = False
            logger.info("redis_client_initialized", mode="redis", url=self._redis_url)
        except Exception as exc:
            self._using_memory = True
            self._redis = None
            logger.warning(
                "redis_fallback_to_memory",
                reason=str(exc),
                mode="in_memory_ttl",
            )

    async def setex(self, name: str, time_sec: int, value: str) -> bool:
        """Set key with expiration in seconds."""
        if not self._using_memory and self._redis is not None:
            try:
                res = await self._redis.setex(name, time_sec, value)
                return bool(res)
            except Exception as exc:
                logger.warning("redis_setex_error_falling_back", error=str(exc))
                self._using_memory = True
        return await self._memory_store.setex(name, time_sec, value)

    async def get(self, name: str) -> str | None:
        """Get value by key."""
        if not self._using_memory and self._redis is not None:
            try:
                val = await self._redis.get(name)
                return str(val) if val is not None else None
            except Exception as exc:
                logger.warning("redis_get_error_falling_back", error=str(exc))
                self._using_memory = True
        return await self._memory_store.get(name)

    async def delete(self, *names: str) -> int:
        """Delete one or more keys."""
        if not self._using_memory and self._redis is not None:
            try:
                res = await self._redis.delete(*names)
                return int(res)
            except Exception as exc:
                logger.warning("redis_delete_error_falling_back", error=str(exc))
                self._using_memory = True
        return await self._memory_store.delete(*names)

    async def keys(self, pattern: str = "*") -> list[str]:
        """List keys matching pattern."""
        if not self._using_memory and self._redis is not None:
            try:
                raw_keys = await self._redis.keys(pattern)
                return sorted(str(k) for k in raw_keys)
            except Exception as exc:
                logger.warning("redis_keys_error_falling_back", error=str(exc))
                self._using_memory = True
        return await self._memory_store.keys(pattern)

    async def ttl(self, name: str) -> int:
        """Return remaining TTL in seconds."""
        if not self._using_memory and self._redis is not None:
            try:
                res = await self._redis.ttl(name)
                return int(res)
            except Exception as exc:
                logger.warning("redis_ttl_error_falling_back", error=str(exc))
                self._using_memory = True
        return await self._memory_store.ttl(name)

    async def ping(self) -> bool:
        """Verify store responsiveness."""
        if not self._using_memory and self._redis is not None:
            try:
                return bool(await self._redis.ping())
            except Exception:
                return False
        return await self._memory_store.ping()

    async def flushdb(self) -> None:
        """Clear all keys in active backend."""
        if not self._using_memory and self._redis is not None:
            try:
                await self._redis.flushdb()
            except Exception:
                pass
        await self._memory_store.flushdb()

    async def close(self) -> None:
        """Close underlying connections."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
        await self._memory_store.close()

