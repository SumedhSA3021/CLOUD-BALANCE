"""Server-side Task Resource Profile Table.

Clients only send `{client_id, task_type}` and NEVER declare CPU or RAM demands.
The Controller resolves `task_type` to a deterministic resource profile here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskType(StrEnum):
    """Supported cloud workload task classifications."""

    CPU_INTENSIVE = "CPU_INTENSIVE"
    MEMORY_INTENSIVE = "MEMORY_INTENSIVE"
    BALANCED_COMPUTE = "BALANCED_COMPUTE"
    LIGHTWEIGHT_QUERY = "LIGHTWEIGHT_QUERY"


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    """Immutable server-side resource specification for a task type."""

    task_type: TaskType
    cpu_demand_pct: float
    mem_demand_mb: float
    matrix_dim: int
    duration_sec: float
    description: str


TASK_PROFILES: dict[TaskType, ResourceProfile] = {
    TaskType.CPU_INTENSIVE: ResourceProfile(
        task_type=TaskType.CPU_INTENSIVE,
        cpu_demand_pct=35.0,
        mem_demand_mb=256.0,
        matrix_dim=2400,
        duration_sec=4.0,
        description="Dense matrix multiplication heavy on CPU cores (35% CPU, 256MB RAM)",
    ),
    TaskType.MEMORY_INTENSIVE: ResourceProfile(
        task_type=TaskType.MEMORY_INTENSIVE,
        cpu_demand_pct=15.0,
        mem_demand_mb=1024.0,
        matrix_dim=4500,
        duration_sec=5.0,
        description="Large tensor allocation and reduction heavy on RAM (15% CPU, 1024MB RAM)",
    ),
    TaskType.BALANCED_COMPUTE: ResourceProfile(
        task_type=TaskType.BALANCED_COMPUTE,
        cpu_demand_pct=25.0,
        mem_demand_mb=512.0,
        matrix_dim=2000,
        duration_sec=3.0,
        description="Balanced compute and memory matrix transformation (25% CPU, 512MB RAM)",
    ),
    TaskType.LIGHTWEIGHT_QUERY: ResourceProfile(
        task_type=TaskType.LIGHTWEIGHT_QUERY,
        cpu_demand_pct=10.0,
        mem_demand_mb=128.0,
        matrix_dim=1000,
        duration_sec=1.5,
        description="Fast low-footprint analytical query (10% CPU, 128MB RAM)",
    ),
}


def resolve_task_profile(task_type: TaskType | str) -> ResourceProfile:
    """Resolve a TaskType (or string representation) to its immutable ResourceProfile.

    Raises:
        ValueError: If the task_type is unknown.
    """
    try:
        enum_type = TaskType(task_type)
    except ValueError as exc:
        valid = ", ".join(t.value for t in TaskType)
        raise ValueError(f"Unknown task_type '{task_type}'. Valid types: {valid}") from exc
    return TASK_PROFILES[enum_type]

