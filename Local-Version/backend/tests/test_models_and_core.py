"""Unit tests for Phase 1 Core Configuration, Storage Fallbacks, Profiles, and Models."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import configure_logging, get_correlation_id, get_logger, set_correlation_id
from app.core.mongo_client import DualMongoClient
from app.core.profiles import TASK_PROFILES, TaskType, resolve_task_profile
from app.core.redis_client import DualRedisClient
from app.core.security import verify_api_key
from app.models.schemas import (
    Task,
    TaskRequest,
    Telemetry,
    WorkerSnapshotItem,
    WorkerStatus,
    compute_worker_status,
)


def test_task_profiles_exact_specifications() -> None:
    """Verify server-side task profiles match exact CPU, RAM, matrix_dim, and duration specs."""
    cpu_p = resolve_task_profile(TaskType.CPU_INTENSIVE)
    assert cpu_p.cpu_demand_pct == 35.0
    assert cpu_p.mem_demand_mb == 256.0
    assert cpu_p.matrix_dim == 2400
    assert cpu_p.duration_sec == 4.0

    mem_p = resolve_task_profile("MEMORY_INTENSIVE")
    assert mem_p.cpu_demand_pct == 15.0
    assert mem_p.mem_demand_mb == 1024.0
    assert mem_p.matrix_dim == 4500
    assert mem_p.duration_sec == 5.0

    bal_p = resolve_task_profile(TaskType.BALANCED_COMPUTE)
    assert bal_p.cpu_demand_pct == 25.0
    assert bal_p.mem_demand_mb == 512.0
    assert bal_p.matrix_dim == 2000
    assert bal_p.duration_sec == 3.0

    light_p = resolve_task_profile(TaskType.LIGHTWEIGHT_QUERY)
    assert light_p.cpu_demand_pct == 10.0
    assert light_p.mem_demand_mb == 128.0
    assert light_p.matrix_dim == 1000
    assert light_p.duration_sec == 1.5

    assert len(TASK_PROFILES) == 4

    with pytest.raises(ValueError, match="Unknown task_type"):
        resolve_task_profile("INVALID_TYPE")


def test_task_request_forbids_extra_fields() -> None:
    """Clients must only send client_id and task_type; extra fields like cpu_demand are rejected."""
    req = TaskRequest(client_id="laptop-1", task_type=TaskType.CPU_INTENSIVE)
    task = Task.from_request(req)
    assert task.client_id == "laptop-1"
    assert task.cpu_demand_pct == 35.0
    assert task.mem_demand_mb == 256.0
    assert task.task_id.startswith("tsk-")

    with pytest.raises(ValidationError):
        TaskRequest.model_validate(
            {
                "client_id": "laptop-1",
                "task_type": "CPU_INTENSIVE",
                "cpu_demand_pct": 1.0,
            }
        )


def test_worker_status_thresholds() -> None:
    """Verify HEALTHY (<60 CPU & <70 RAM), MODERATE (60-84 CPU or 70-89 RAM), CRITICAL (>=85 CPU or >=90 RAM)."""
    assert compute_worker_status(25.0, 40.0) == WorkerStatus.HEALTHY
    assert compute_worker_status(59.9, 69.9) == WorkerStatus.HEALTHY
    assert compute_worker_status(60.0, 50.0) == WorkerStatus.MODERATE
    assert compute_worker_status(50.0, 70.0) == WorkerStatus.MODERATE
    assert compute_worker_status(84.9, 89.9) == WorkerStatus.MODERATE
    assert compute_worker_status(85.0, 20.0) == WorkerStatus.CRITICAL
    assert compute_worker_status(20.0, 90.0) == WorkerStatus.CRITICAL
    assert compute_worker_status(95.0, 95.0) == WorkerStatus.CRITICAL


def test_worker_snapshot_item_from_telemetry() -> None:
    """Verify WorkerSnapshotItem combines live telemetry with in-flight reservations."""
    t = Telemetry(
        worker_id="worker-1",
        ip_address="10.128.0.11",
        port=8001,
        cpu_percent=50.0,
        memory_total_mb=4096.0,
        memory_used_mb=2048.0,
        memory_percent=50.0,
        load_avg_1m=1.2,
        active_task_count=2,
    )
    snap = WorkerSnapshotItem.from_telemetry(
        t, in_flight_cpu_pct=15.0, in_flight_mem_mb=512.0, in_flight_tasks=1
    )
    assert snap.cpu_percent == 65.0
    assert snap.memory_used_mb == 2560.0
    assert snap.active_tasks == 3
    assert snap.status == WorkerStatus.MODERATE


def test_settings_and_logging() -> None:
    """Verify Settings parsing and structured logging correlation IDs."""
    s = Settings(allowed_origins="http://a.com, http://b.com")  # type: ignore[arg-type]
    assert s.allowed_origins == ["http://a.com", "http://b.com"]

    configure_logging(json_logs=True)
    cid = set_correlation_id("test-cid-123")
    assert get_correlation_id() == "test-cid-123"
    assert cid == "test-cid-123"
    log = get_logger("test")
    log.info("test_event", ok=True)


@pytest.mark.asyncio
async def test_api_key_security() -> None:
    """Verify API key validation in both optional and strict modes."""
    settings_strict = Settings(api_key="secret-123", require_api_key=True)
    assert await verify_api_key("secret-123", settings_strict) == "secret-123"

    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key("wrong-key", settings_strict)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info2:
        await verify_api_key(None, settings_strict)
    assert exc_info2.value.status_code == 401

    settings_demo = Settings(api_key="secret-123", require_api_key=False)
    assert await verify_api_key(None, settings_demo) == "anonymous-allowed"


@pytest.mark.asyncio
async def test_dual_redis_in_memory_ttl_store() -> None:
    """Verify DualRedisClient TTL expiration, pattern matching, and deletion."""
    client = DualRedisClient(force_memory=True)
    await client.connect()
    assert client.backend_mode == "in_memory_ttl"
    assert await client.ping() is True

    await client.setex("cluster:worker:w1", 10, '{"worker_id":"w1"}')
    await client.setex("cluster:worker:w2", 1, '{"worker_id":"w2"}')

    keys = await client.keys("cluster:worker:*")
    assert keys == ["cluster:worker:w1", "cluster:worker:w2"]
    assert await client.get("cluster:worker:w1") == '{"worker_id":"w1"}'
    assert await client.ttl("cluster:worker:w1") > 0

    # Wait for w2 TTL to expire
    await asyncio.sleep(1.1)
    assert await client.get("cluster:worker:w2") is None
    assert await client.keys("cluster:worker:*") == ["cluster:worker:w1"]

    await client.delete("cluster:worker:w1")
    assert await client.get("cluster:worker:w1") is None
    await client.flushdb()
    await client.close()


@pytest.mark.asyncio
async def test_dual_mongo_sqlite_fallback() -> None:
    """Verify DualMongoClient SQLite persistence for assignments and benchmark runs."""
    mongo = DualMongoClient(force_sqlite=True)
    await mongo.connect()
    assert mongo.backend_mode == "sqlite_fallback"
    assert await mongo.ping() is True

    await mongo.insert_assignment(
        {"task_id": "tsk-1", "client_id": "laptop-1", "timestamp": "2026-11-11T00:00:00Z"}
    )
    await mongo.insert_assignment(
        {"task_id": "tsk-2", "client_id": "laptop-2", "timestamp": "2026-11-11T00:00:01Z"}
    )

    recent = await mongo.find_recent_assignments(limit=10)
    assert len(recent) == 2
    assert recent[0]["task_id"] == "tsk-2"
    assert recent[1]["task_id"] == "tsk-1"

    await mongo.insert_benchmark_run(
        {"run_id": "bench-1", "created_at": "2026-11-11T00:00:00Z", "seed": 42}
    )
    runs = await mongo.find_benchmark_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "bench-1"

    await mongo.clear()
    assert await mongo.find_recent_assignments() == []
    await mongo.close()

