"""Strict Pydantic v2 Data Contracts for CloudBalance (/api/v1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.profiles import TaskType, resolve_task_profile


class WorkerStatus(StrEnum):
    """Health classification for worker VMs based on CPU and RAM utilization."""

    HEALTHY = "HEALTHY"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"


class SchedulerName(StrEnum):
    """Supported pluggable scheduling algorithms."""

    ORTOOLS_MILP = "ortools_milp"
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"


class TaskStatus(StrEnum):
    """Lifecycle states of a client task."""

    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED_ASSIGNED = "DEGRADED_ASSIGNED"


def compute_worker_status(cpu_percent: float, memory_percent: float) -> WorkerStatus:
    """Classify worker health according to strict SLA thresholds:
    - CRITICAL: cpu >= 85 or ram >= 90
    - MODERATE: cpu in [60, 85) or ram in [70, 90)
    - HEALTHY: cpu < 60 and ram < 70
    """
    if cpu_percent >= 85.0 or memory_percent >= 90.0:
        return WorkerStatus.CRITICAL
    if cpu_percent >= 60.0 or memory_percent >= 70.0:
        return WorkerStatus.MODERATE
    return WorkerStatus.HEALTHY


class TaskRequest(BaseModel):
    """Inbound payload sent by client laptops to POST /api/v1/tasks.
    Clients NEVER specify CPU or RAM; they only declare client_id and task_type.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-\.]+$",
        description="Identifier of the sending client laptop (e.g. laptop-alpha)",
    )
    task_type: TaskType = Field(
        ...,
        description="Server-resolved workload profile type",
    )

    @field_validator("client_id", mode="before")
    @classmethod
    def sanitize_client_id(cls, value: object) -> object:
        """Sanitize spaces or mobile keyboard punctuation in client_id so mobile browsers never 422."""
        if isinstance(value, str):
            import re

            cleaned = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", value.strip())
            cleaned = re.sub(r"-+", "-", cleaned).strip("-")
            return cleaned or "mobile-client"
        return value


class Task(BaseModel):
    """Internal enriched task representation after resolving server-side resource profile."""

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=lambda: f"tsk-{uuid.uuid4().hex[:10]}")
    client_id: str
    task_type: TaskType
    cpu_demand_pct: float = Field(..., gt=0.0, le=100.0)
    mem_demand_mb: float = Field(..., gt=0.0)
    duration_sec: float = Field(..., gt=0.0)
    matrix_dim: int = Field(..., ge=10)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    queued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_request(cls, req: TaskRequest, now: datetime | None = None) -> Task:
        """Create an immutable internal Task by resolving the server-side profile table."""
        profile = resolve_task_profile(req.task_type)
        ts = now or datetime.now(UTC)
        return cls(
            client_id=req.client_id,
            task_type=req.task_type,
            cpu_demand_pct=profile.cpu_demand_pct,
            mem_demand_mb=profile.mem_demand_mb,
            duration_sec=profile.duration_sec,
            matrix_dim=profile.matrix_dim,
            created_at=ts,
            queued_at=ts,
        )


class TaskSubmissionResponse(BaseModel):
    """Response returned to clients upon task submission."""

    model_config = ConfigDict(frozen=True)

    accepted: bool = True
    task_id: str
    client_id: str
    task_type: TaskType
    cpu_demand_pct: float
    mem_demand_mb: float
    duration_sec: float
    matrix_dim: int
    queue_depth: int
    queued_at: datetime


class Telemetry(BaseModel):
    """Heartbeat and utilization payload sent by worker psutil agent every 2s."""

    model_config = ConfigDict(frozen=True)

    worker_id: str = Field(..., min_length=1, max_length=64)
    ip_address: str = Field(..., min_length=1, max_length=128)
    port: int = Field(default=8001, ge=1, le=65535)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cpu_percent: float = Field(..., ge=0.0, le=100.0)
    memory_total_mb: float = Field(..., gt=0.0)
    memory_used_mb: float = Field(..., ge=0.0)
    memory_percent: float = Field(..., ge=0.0, le=100.0)
    load_avg_1m: float = Field(..., ge=0.0)
    active_task_count: int = Field(..., ge=0)

    @field_validator("memory_used_mb")
    @classmethod
    def validate_memory_used(cls, v: float) -> float:
        return round(v, 2)


class WorkerSnapshotItem(BaseModel):
    """Worker card representation inside ClusterSnapshot."""

    model_config = ConfigDict(frozen=True)

    worker_id: str
    ip_address: str = "127.0.0.1"
    port: int = 8001
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    active_tasks: int
    status: WorkerStatus
    load_avg_1m: float = 0.0
    in_flight_cpu_pct: float = 0.0
    in_flight_mem_mb: float = 0.0

    @classmethod
    def from_telemetry(
        cls,
        telemetry: Telemetry,
        in_flight_cpu_pct: float = 0.0,
        in_flight_mem_mb: float = 0.0,
        in_flight_tasks: int = 0,
    ) -> WorkerSnapshotItem:
        effective_cpu = min(100.0, round(telemetry.cpu_percent + in_flight_cpu_pct, 2))
        effective_mem_used = min(
            telemetry.memory_total_mb,
            round(telemetry.memory_used_mb + in_flight_mem_mb, 2),
        )
        effective_mem_pct = min(
            100.0,
            round((effective_mem_used / telemetry.memory_total_mb) * 100.0, 2),
        )
        active = telemetry.active_task_count + in_flight_tasks
        return cls(
            worker_id=telemetry.worker_id,
            ip_address=telemetry.ip_address,
            port=telemetry.port,
            cpu_percent=effective_cpu,
            memory_percent=effective_mem_pct,
            memory_used_mb=effective_mem_used,
            memory_total_mb=round(telemetry.memory_total_mb, 2),
            active_tasks=active,
            status=compute_worker_status(effective_cpu, effective_mem_pct),
            load_avg_1m=round(telemetry.load_avg_1m, 2),
            in_flight_cpu_pct=round(in_flight_cpu_pct, 2),
            in_flight_mem_mb=round(in_flight_mem_mb, 2),
        )


class DispatchPayload(BaseModel):
    """Payload dispatched from Controller to internal Worker VM (:8001/execute)."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    duration_sec: float = Field(..., gt=0.0, le=60.0)
    matrix_dim: int = Field(..., ge=10, le=10000)
    cpu_demand_pct: float = Field(default=25.0, ge=0.0, le=100.0)
    mem_demand_mb: float = Field(default=256.0, ge=0.0)


class WorkerExecutionResponse(BaseModel):
    """Response returned by Worker VM after running np.dot workload."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    worker_id: str
    status: str = "COMPLETED"
    execution_ms: float
    matrix_dim: int
    checksum: float


class Assignment(BaseModel):
    """Record of a task assignment decision and dispatch outcome."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    client_id: str
    task_type: TaskType
    cpu_demand_pct: float = 0.0
    mem_demand_mb: float = 0.0
    assigned_worker_id: str
    scheduler: str
    solver_latency_ms: float
    queue_wait_ms: float
    execution_ms: float = 0.0
    status: str = "ASSIGNED"
    degraded: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SchedulerDecisionMeta(BaseModel):
    """Diagnostic metadata produced by a scheduler batch run."""

    model_config = ConfigDict(frozen=True)

    scheduler: str
    status: str
    solver_latency_ms: float
    projected_peak_cpu: float
    projected_peak_mem_pct: float = 0.0
    degraded: bool = False
    warning: str | None = None


class ClientStats(BaseModel):
    """Per-client real-time traffic and worker distribution telemetry."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    req_per_sec: float
    queued: int
    total_sent: int = 0
    avg_queue_wait_ms: float = 0.0
    served_by: dict[str, int] = Field(default_factory=dict)


class ClusterSnapshot(BaseModel):
    """WebSocket payload broadcast every 1.5s to all connected dashboards."""

    model_config = ConfigDict(frozen=True)

    type: str = "CLUSTER_SNAPSHOT"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    workers: list[WorkerSnapshotItem]
    recent_assignments: list[Assignment]
    clients: list[ClientStats]
    queue_depth: int
    active_scheduler: str
    lambda_total: float
    avg_solver_latency_ms: float = 0.0
    degraded_mode: bool = False
    degraded_warning: str | None = None
    paused: bool = False


class SchedulerControlRequest(BaseModel):
    """Request payload for hot-swapping active scheduler at runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheduler: SchedulerName


class TrafficControlRequest(BaseModel):
    """Request payload for adjusting global lambda, pausing, or injecting a burst."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lambda_rate: float | None = Field(default=None, ge=0.0, le=200.0)
    paused: bool | None = None
    spike_tasks: int | None = Field(default=None, ge=1, le=100)
    spike_client_id: str = "ops-spike-injector"
    spike_task_type: TaskType = TaskType.CPU_INTENSIVE


class SchedulerBenchmarkMetrics(BaseModel):
    """Aggregated benchmark metrics for a single scheduler over the replay trace."""

    model_config = ConfigDict(frozen=True)

    scheduler: str
    total_tasks: int
    completed_tasks: int
    degraded_assignments: int
    cpu_stddev_mean: float
    cpu_stddev_max: float
    peak_cpu_pct: float
    peak_mem_pct: float
    cpu_cap_violations: int
    mem_cap_violations: int
    total_cap_violations: int
    mean_completion_latency_ms: float
    p95_completion_latency_ms: float
    mean_solver_latency_ms: float
    p95_solver_latency_ms: float
    throughput_tasks_per_sec: float
    time_series_cpu_stddev: list[float] = Field(default_factory=list)
    time_series_peak_cpu: list[float] = Field(default_factory=list)
    worker_assignment_counts: dict[str, int] = Field(default_factory=dict)


class BenchmarkRun(BaseModel):
    """Complete multi-scheduler benchmark comparison run."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: f"bench-{uuid.uuid4().hex[:8]}")
    seed: int
    total_tasks: int
    duration_sec: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    results: dict[str, SchedulerBenchmarkMetrics]
    markdown_table: str = ""

