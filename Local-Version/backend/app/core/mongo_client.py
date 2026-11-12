"""Dual-mode Async MongoDB Client with SQLite Fallback for Zero-Cloud Local Execution."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.logging import get_logger

logger = get_logger("mongo_client")


class SQLiteFallbackStore:
    """Thread/async-safe SQLite store implementing document persistence for local mode."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._lock = asyncio.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    async def insert_assignment(self, doc: dict[str, Any]) -> None:
        """Persist a task assignment document."""
        payload = json.dumps(doc, default=str)
        task_id = str(doc.get("task_id", ""))
        created_at = str(doc.get("timestamp", ""))
        async with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO assignments (task_id, created_at, payload) VALUES (?, ?, ?)",
                    (task_id, created_at, payload),
                )

    async def find_recent_assignments(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch most recent task assignments ordered newest first."""
        async with self._lock:
            cursor = self._conn.execute(
                "SELECT payload FROM assignments ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def insert_benchmark_run(self, doc: dict[str, Any]) -> None:
        """Persist a benchmark run summary document."""
        payload = json.dumps(doc, default=str)
        run_id = str(doc.get("run_id", ""))
        created_at = str(doc.get("created_at", ""))
        async with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO benchmark_runs (run_id, created_at, payload) VALUES (?, ?, ?)",
                    (run_id, created_at, payload),
                )

    async def find_benchmark_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch recent benchmark runs ordered newest first."""
        async with self._lock:
            cursor = self._conn.execute(
                "SELECT payload FROM benchmark_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def clear(self) -> None:
        """Delete all stored documents."""
        async with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM assignments")
                self._conn.execute("DELETE FROM benchmark_runs")

    async def ping(self) -> bool:
        """Verify SQLite connection health."""
        async with self._lock:
            cursor = self._conn.execute("SELECT 1")
            return cursor.fetchone() == (1,)

    async def close(self) -> None:
        """Close SQLite connection."""
        async with self._lock:
            self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class DualMongoClient:
    """Unified persistence client using Motor (MongoDB) when configured or SQLite in local mode."""

    def __init__(
        self,
        mongo_url: str = "mongodb://localhost:27017",
        db_name: str = "cloudbalance",
        force_sqlite: bool = False,
        sqlite_path: str = ":memory:",
    ) -> None:
        self._mongo_url = mongo_url
        self._db_name = db_name
        self._force_sqlite = force_sqlite
        self._sqlite = SQLiteFallbackStore(db_path=sqlite_path)
        self._client: AsyncIOMotorClient[Any] | None = None
        self._db: Any = None
        self._using_sqlite: bool = True

    @property
    def backend_mode(self) -> str:
        """Return 'sqlite_fallback' or 'mongodb'."""
        return "sqlite_fallback" if self._using_sqlite else "mongodb"

    async def connect(self) -> None:
        """Attempt connection to MongoDB unless forced to SQLite fallback."""
        if self._force_sqlite:
            self._using_sqlite = True
            logger.info("mongo_client_initialized", mode="sqlite_fallback")
            return

        try:
            client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
                self._mongo_url,
                serverSelectionTimeoutMS=1500,
                connectTimeoutMS=1500,
            )
            await client.admin.command("ping")
            self._client = client
            self._db = client[self._db_name]
            self._using_sqlite = False
            logger.info("mongo_client_initialized", mode="mongodb", db=self._db_name)
        except Exception as exc:
            self._using_sqlite = True
            self._client = None
            self._db = None
            logger.warning(
                "mongo_fallback_to_sqlite",
                reason=str(exc),
                mode="sqlite_fallback",
            )

    async def insert_assignment(self, doc: dict[str, Any]) -> None:
        """Insert a task assignment record."""
        clean_doc = dict(doc)
        if not self._using_sqlite and self._db is not None:
            try:
                await self._db["assignments"].insert_one(dict(clean_doc))
                return
            except Exception as exc:
                logger.warning("mongo_insert_error_falling_back", error=str(exc))
                self._using_sqlite = True
        await self._sqlite.insert_assignment(clean_doc)

    async def find_recent_assignments(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent assignments ordered newest first."""
        if not self._using_sqlite and self._db is not None:
            try:
                cursor = (
                    self._db["assignments"]
                    .find({}, {"_id": 0})
                    .sort("timestamp", -1)
                    .limit(limit)
                )
                return list(await cursor.to_list(length=limit))
            except Exception as exc:
                logger.warning("mongo_find_error_falling_back", error=str(exc))
                self._using_sqlite = True
        return await self._sqlite.find_recent_assignments(limit=limit)

    async def insert_benchmark_run(self, doc: dict[str, Any]) -> None:
        """Insert a benchmark run summary."""
        clean_doc = dict(doc)
        if not self._using_sqlite and self._db is not None:
            try:
                await self._db["benchmark_runs"].insert_one(dict(clean_doc))
                return
            except Exception as exc:
                logger.warning("mongo_insert_bench_error_falling_back", error=str(exc))
                self._using_sqlite = True
        await self._sqlite.insert_benchmark_run(clean_doc)

    async def find_benchmark_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent benchmark runs ordered newest first."""
        if not self._using_sqlite and self._db is not None:
            try:
                cursor = (
                    self._db["benchmark_runs"]
                    .find({}, {"_id": 0})
                    .sort("created_at", -1)
                    .limit(limit)
                )
                return list(await cursor.to_list(length=limit))
            except Exception as exc:
                logger.warning("mongo_find_bench_error_falling_back", error=str(exc))
                self._using_sqlite = True
        return await self._sqlite.find_benchmark_runs(limit=limit)

    async def clear(self) -> None:
        """Clear stored records."""
        if not self._using_sqlite and self._db is not None:
            try:
                await self._db["assignments"].delete_many({})
                await self._db["benchmark_runs"].delete_many({})
            except Exception:
                pass
        await self._sqlite.clear()

    async def ping(self) -> bool:
        """Health check."""
        if not self._using_sqlite and self._client is not None:
            try:
                await self._client.admin.command("ping")
                return True
            except Exception:
                return False
        return await self._sqlite.ping()

    async def close(self) -> None:
        """Close underlying connections."""
        if self._client is not None:
            self._client.close()
        await self._sqlite.close()
