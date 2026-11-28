"""Cluster State Service backed by Redis TTL keys (`cluster:worker:{id}`)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.core.redis_client import DualRedisClient
from app.models.schemas import Telemetry, WorkerSnapshotItem
from app.schedulers.base import InFlightTracker

logger = get_logger("service.cluster_state")

WORKER_KEY_PREFIX = "cluster:worker:"


class ClusterStateService:
    """Manages live worker telemetry state in Redis with automatic 10s TTL expiration."""

    def __init__(
        self,
        redis_client: DualRedisClient,
        in_flight_tracker: InFlightTracker,
        ttl_seconds: int = 10,
    ) -> None:
        self._redis = redis_client
        self._in_flight = in_flight_tracker
        self._ttl_seconds = ttl_seconds
        self._killed_workers: set[str] = set()

    @staticmethod
    def worker_key(worker_id: str) -> str:
        """Format canonical Redis key `cluster:worker:{worker_id}`."""
        return f"{WORKER_KEY_PREFIX}{worker_id}"

    async def update_telemetry(self, telemetry: Telemetry) -> bool:
        """Persist worker telemetry in Redis with `SETEX cluster:worker:{id} 10 <json>`.

        Returns False if the worker is currently marked simulated-dead via kill control.
        """
        if telemetry.worker_id in self._killed_workers:
            return False

        if telemetry.active_task_count > 0:
            self._in_flight.release_worker(telemetry.worker_id)

        key = self.worker_key(telemetry.worker_id)
        payload = telemetry.model_dump_json()
        await self._redis.setex(key, self._ttl_seconds, payload)
        return True

    async def get_active_workers(self) -> list[Telemetry]:
        """Read all non-expired `cluster:worker:*` keys from Redis, sorted by worker_id."""
        keys = await self._redis.keys(f"{WORKER_KEY_PREFIX}*")
        workers: list[Telemetry] = []
        for key in sorted(keys):
            raw = await self._redis.get(key)
            if not raw:
                continue
            try:
                t = Telemetry.model_validate_json(raw)
                if t.worker_id not in self._killed_workers:
                    workers.append(t)
            except Exception as exc:
                logger.warning("invalid_worker_telemetry_json", key=key, error=str(exc))
        workers.sort(key=lambda w: w.worker_id)
        return workers

    async def get_worker_snapshots(self) -> list[WorkerSnapshotItem]:
        """Return enriched WorkerSnapshotItems combining Redis telemetry + in-flight load."""
        workers = await self.get_active_workers()
        snapshots: list[WorkerSnapshotItem] = []
        for w in workers:
            if_cpu, if_mem, if_tasks = self._in_flight.get_worker_in_flight(w.worker_id)
            snapshots.append(
                WorkerSnapshotItem.from_telemetry(
                    w,
                    in_flight_cpu_pct=if_cpu,
                    in_flight_mem_mb=if_mem,
                    in_flight_tasks=if_tasks,
                )
            )
        return snapshots

    async def evict_worker(self, worker_id: str) -> None:
        """Immediately remove a failed worker's key from Redis for instant failover."""
        await self._redis.delete(self.worker_key(worker_id))
        logger.warning("worker_evicted_from_cluster", worker_id=worker_id)

    async def kill_worker(self, worker_id: str) -> None:
        """Simulate killing a worker VM: evict from Redis and block heartbeats until revived."""
        self._killed_workers.add(worker_id)
        await self.evict_worker(worker_id)
        logger.warning("worker_simulated_kill", worker_id=worker_id)

    async def revive_worker(self, worker_id: str) -> None:
        """Revive a previously killed worker VM and re-seed baseline telemetry if virtual."""
        self._killed_workers.discard(worker_id)
        logger.info("worker_revived", worker_id=worker_id)

    @property
    def killed_workers(self) -> set[str]:
        """Return set of worker IDs currently simulated as dead."""
        return set(self._killed_workers)

    async def seed_virtual_workers_if_empty(self, force_missing: bool = False) -> list[Telemetry]:
        """Seed 3 virtual workers with distinct profiles when running in standalone local mode."""
        existing = await self.get_active_workers()
        if existing and not force_missing:
            return existing
        if existing and any(w.ip_address != "virtual" for w in existing):
            return existing

        existing_ids = {w.worker_id for w in existing}
        defaults = [
            Telemetry(
                worker_id="worker-1",
                ip_address="virtual",
                port=8001,
                timestamp=datetime.now(UTC),
                cpu_percent=12.5,
                memory_total_mb=4096.0,
                memory_used_mb=640.0,
                memory_percent=15.6,
                load_avg_1m=0.45,
                active_task_count=0,
            ),
            Telemetry(
                worker_id="worker-2",
                ip_address="virtual",
                port=8002,
                timestamp=datetime.now(UTC),
                cpu_percent=18.0,
                memory_total_mb=4096.0,
                memory_used_mb=820.0,
                memory_percent=20.0,
                load_avg_1m=0.68,
                active_task_count=0,
            ),
            Telemetry(
                worker_id="worker-3",
                ip_address="virtual",
                port=8003,
                timestamp=datetime.now(UTC),
                cpu_percent=9.0,
                memory_total_mb=8192.0,
                memory_used_mb=1024.0,
                memory_percent=12.5,
                load_avg_1m=0.32,
                active_task_count=0,
            ),
        ]
        seeded: list[Telemetry] = list(existing)
        for w in defaults:
            if w.worker_id not in self._killed_workers and w.worker_id not in existing_ids:
                await self.update_telemetry(w)
                seeded.append(w)
        return seeded

