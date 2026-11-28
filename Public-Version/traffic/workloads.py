"""Workload Mix Distributions and Dynamic Arrival Rate Scenarios."""

from __future__ import annotations

import math
import random
from enum import StrEnum


class WorkloadMix(StrEnum):
    """Named workload profiles for client laptops."""

    CPU = "cpu"
    MEM = "mem"
    BALANCED = "balanced"


class ScenarioType(StrEnum):
    """Temporal arrival rate modulation profiles."""

    STEADY = "steady"
    BURST = "burst"
    RAMP = "ramp"


TASK_TYPES: tuple[str, ...] = (
    "CPU_INTENSIVE",
    "MEMORY_INTENSIVE",
    "BALANCED_COMPUTE",
    "LIGHTWEIGHT_QUERY",
)

# Probability weights for (CPU_INTENSIVE, MEMORY_INTENSIVE, BALANCED_COMPUTE, LIGHTWEIGHT_QUERY)
MIX_WEIGHTS: dict[WorkloadMix, tuple[float, float, float, float]] = {
    # Laptop A: Heavy CPU pressure (65% CPU_INTENSIVE)
    WorkloadMix.CPU: (0.65, 0.10, 0.15, 0.10),
    # Laptop B: Heavy RAM pressure (65% MEMORY_INTENSIVE)
    WorkloadMix.MEM: (0.10, 0.65, 0.15, 0.10),
    # Laptop C: Balanced heterogeneous mix
    WorkloadMix.BALANCED: (0.25, 0.25, 0.30, 0.20),
}


def sample_task_type(mix: WorkloadMix | str, rng: random.Random) -> str:
    """Sample a single task_type string using `rng` and the specified `WorkloadMix`."""
    resolved_mix = WorkloadMix(mix)
    weights = MIX_WEIGHTS[resolved_mix]
    chosen = rng.choices(TASK_TYPES, weights=weights, k=1)[0]
    return str(chosen)


def compute_scenario_lambda(
    base_lambda: float,
    scenario: ScenarioType | str,
    elapsed_sec: float,
    total_duration_sec: float = 30.0,
) -> float:
    """Compute instantaneous arrival rate lambda(t) for the given scenario.

    - `steady`: Constant `base_lambda`.
    - `burst`: Alternates between `base_lambda` baseline and `3.0 * base_lambda` burst windows.
    - `ramp`: Linearly ramps from `0.5 * base_lambda` up to `2.5 * base_lambda` then steps down.
    """
    if base_lambda <= 0.0:
        return 0.0

    resolved = ScenarioType(scenario)
    if resolved == ScenarioType.STEADY:
        return base_lambda

    if resolved == ScenarioType.BURST:
        # Periodic 10s cycle: 0..6s normal, 6..9s 3x spike, 9..10s cooldown
        phase = elapsed_sec % 10.0
        if 6.0 <= phase < 9.0:
            return base_lambda * 3.0
        if phase >= 9.0:
            return base_lambda * 0.6
        return base_lambda

    # RAMP scenario
    span = max(1.0, total_duration_sec)
    progress = min(1.0, max(0.0, elapsed_sec / span))
    # Smooth triangle/sawtooth ramp peaking at 75% progress
    if progress <= 0.75:
        factor = 0.5 + (2.0 * (progress / 0.75))
    else:
        factor = 2.5 - (1.5 * ((progress - 0.75) / 0.25))
    return max(0.1, round(base_lambda * factor, 4) if not math.isnan(factor) else base_lambda)

