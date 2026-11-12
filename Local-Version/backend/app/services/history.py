"""Assignment & Benchmark History Service backed by DualMongoClient and Ring Buffer."""

from __future__ import annotations

from collections import deque

from app.core.mongo_client import DualMongoClient
from app.core.redis_client import DualRedisClient
from app.models.schemas import Assignment, BenchmarkRun


class HistoryService:
    """Persists task assignments and benchmark runs while keeping a fast in-memory ring buffer."""

    def __init__(
        self,
        mongo_client: DualMongoClient,
        redis_client: DualRedisClient | None = None,
        max_recent: int = 100,
    ) -> None:
        self._mongo = mongo_client
        self._redis = redis_client
        self._recent_assignments: deque[Assignment] = deque(maxlen=max_recent)
        self._solver_latencies_ms: deque[float] = deque(maxlen=100)
        self._benchmark_runs: deque[BenchmarkRun] = deque(maxlen=20)
        self._last_degraded: bool = False
        self._last_warning: str | None = None

    async def record_assignment(
        self,
        assignment: Assignment,
        warning: str | None = None,
    ) -> None:
        """Save assignment in ring buffer, mirror to Redis TTL key, and persist to MongoDB / SQLite."""
        self._recent_assignments.appendleft(assignment)
        self._solver_latencies_ms.append(assignment.solver_latency_ms)
        self._last_degraded = assignment.degraded
        if warning is not None:
            self._last_warning = warning
        elif not assignment.degraded:
            self._last_warning = None

        if self._redis is not None:
            await self._redis.setex(
                f"cluster:assignment:{assignment.task_id}",
                300,
                assignment.model_dump_json(),
            )
        await self._mongo.insert_assignment(assignment.model_dump(mode="json"))

    def update_assignment_status(
        self,
        task_id: str,
        status: str,
        execution_ms: float = 0.0,
        assigned_worker_id: str | None = None,
    ) -> Assignment | None:
        """Create updated immutable Assignment copy in ring buffer upon completion/failover."""
        for idx, existing in enumerate(self._recent_assignments):
            if existing.task_id == task_id:
                updated = existing.model_copy(
                    update={
                        "status": status,
                        "execution_ms": round(execution_ms, 2),
                        "assigned_worker_id": assigned_worker_id or existing.assigned_worker_id,
                    }
                )
                self._recent_assignments[idx] = updated
                return updated
        return None

    async def sync_assignment_to_redis(self, assignment: Assignment | None) -> None:
        """Persist updated assignment state to Redis TTL store."""
        if assignment is not None and self._redis is not None:
            await self._redis.setex(
                f"cluster:assignment:{assignment.task_id}",
                300,
                assignment.model_dump_json(),
            )

    def get_recent_assignments(
        self,
        limit: int = 20,
        client_id: str | None = None,
    ) -> list[Assignment]:
        """Return up to `limit` newest assignments (optionally filtered by `client_id`)."""
        items = list(self._recent_assignments)
        if client_id:
            items = [a for a in items if a.client_id == client_id]
        return items[:limit]

    def get_avg_solver_latency_ms(self) -> float:
        """Return rolling average solver latency in milliseconds."""
        if not self._solver_latencies_ms:
            return 0.0
        return round(sum(self._solver_latencies_ms) / len(self._solver_latencies_ms), 3)

    @property
    def degraded_mode(self) -> bool:
        return self._last_degraded

    @property
    def degraded_warning(self) -> str | None:
        return self._last_warning

    async def record_benchmark_run(self, run: BenchmarkRun) -> None:
        """Persist a benchmark comparison run."""
        self._benchmark_runs.appendleft(run)
        await self._mongo.insert_benchmark_run(run.model_dump(mode="json"))

    async def get_benchmark_runs(self, limit: int = 10) -> list[BenchmarkRun]:
        """Return recent benchmark runs from memory or persistent store."""
        if self._benchmark_runs:
            return list(self._benchmark_runs)[:limit]
        docs = await self._mongo.find_benchmark_runs(limit=limit)
        runs: list[BenchmarkRun] = []
        for doc in docs:
            try:
                runs.append(BenchmarkRun.model_validate(doc))
            except Exception:
                pass
        return runs

