"""Seedable Async Poisson Traffic Generator and Multi-Client Superposition Engine.

Mathematical Foundation:
------------------------
1. Inverse-Transform Sampling for Exponential Inter-Arrival Times:
   Given a homogeneous Poisson process with arrival rate $\\lambda > 0$ (tasks/second),
   the inter-arrival times $\\Delta t_k$ are i.i.d. $\\text{Exponential}(\\lambda)$ random variables
   with cumulative distribution function $F(t) = 1 - e^{-\\lambda t}$.
   Drawing $U \\sim \\text{Uniform}[0, 1)$, we invert $F$ via:
       $$\\Delta t = \\frac{-\\ln(1 - U)}{\\lambda}$$

2. Superposition Theorem of Independent Poisson Processes:
   If $M$ independent client laptops generate Poisson task streams with rates
   $\\lambda_1, \\lambda_2, \\dots, \\lambda_M$, then the merged arrival stream at the
   CloudBalance Controller is itself an exact Poisson process with combined rate:
       $$\\Lambda_{\\text{total}} = \\sum_{m=1}^{M} \\lambda_m$$
   Furthermore, each arrival in the superposed stream originates from client $m$
   with probability $p_m = \\lambda_m / \\Lambda_{\\text{total}}$.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from traffic.workloads import ScenarioType, WorkloadMix, compute_scenario_lambda, sample_task_type


@dataclass(frozen=True, slots=True)
class GeneratedTaskEvent:
    """Single deterministic task arrival event in a Poisson stream."""

    sequence_num: int
    arrival_time_sec: float
    inter_arrival_sec: float
    client_id: str
    task_type: str
    instantaneous_lambda: float


@dataclass(slots=True)
class TrafficRunSummary:
    """Summary statistics from a live or dry-run Poisson traffic session."""

    client_id: str
    sent_count: int = 0
    accepted_count: int = 0
    backpressured_429_count: int = 0
    error_count: int = 0
    elapsed_sec: float = 0.0
    effective_rate_per_sec: float = 0.0
    task_type_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClientStreamConfig:
    """Configuration for one client stream in a multi-client superposition."""

    client_id: str
    base_lambda: float
    mix: WorkloadMix = WorkloadMix.BALANCED
    scenario: ScenarioType = ScenarioType.STEADY
    max_tasks: int = 50
    seed: int = 42


def sample_exponential_dt(lambda_rate: float, rng: random.Random) -> float:
    """Compute exact inter-arrival delay dt = -ln(1 - U) / lambda.

    Raises:
        ValueError: If `lambda_rate <= 0`.
    """
    if lambda_rate <= 0.0:
        raise ValueError(f"lambda_rate must be positive, got {lambda_rate}")
    u = rng.random()  # u in [0.0, 1.0)
    # Guard against theoretical u == 1.0 edge
    u = min(u, 1.0 - 1e-12)
    return -math.log(1.0 - u) / lambda_rate


class PoissonTrafficGenerator:
    """Seedable async Poisson task generator with live-mutable arrival rate lambda."""

    def __init__(
        self,
        client_id: str = "laptop-alpha",
        lambda_rate: float = 5.0,
        mix: WorkloadMix | str = WorkloadMix.BALANCED,
        scenario: ScenarioType | str = ScenarioType.STEADY,
        seed: int | None = 42,
    ) -> None:
        if lambda_rate <= 0.0:
            raise ValueError("Initial lambda_rate must be > 0")
        self.client_id = client_id
        self._lambda_rate = float(lambda_rate)
        self.mix = WorkloadMix(mix)
        self.scenario = ScenarioType(scenario)
        self.seed = seed
        self._rng = random.Random(seed)
        self._stop_requested = False

    @property
    def lambda_rate(self) -> float:
        """Current base arrival rate (tasks/sec)."""
        return self._lambda_rate

    def set_lambda(self, new_lambda: float) -> None:
        """Dynamically update arrival rate lambda at runtime."""
        if new_lambda <= 0.0:
            raise ValueError("new_lambda must be > 0")
        self._lambda_rate = float(new_lambda)

    def stop(self) -> None:
        """Signal live stream loop to terminate cleanly."""
        self._stop_requested = True

    def generate_trace(
        self,
        max_tasks: int = 100,
        total_duration_sec: float = 30.0,
    ) -> list[GeneratedTaskEvent]:
        """Deterministically pre-compute a seeded trace of `max_tasks` events without sleeping."""
        events: list[GeneratedTaskEvent] = []
        current_time = 0.0
        for seq in range(1, max_tasks + 1):
            inst_lambda = compute_scenario_lambda(
                self._lambda_rate,
                self.scenario,
                elapsed_sec=current_time,
                total_duration_sec=total_duration_sec,
            )
            dt = sample_exponential_dt(inst_lambda, self._rng)
            current_time += dt
            t_type = sample_task_type(self.mix, self._rng)
            events.append(
                GeneratedTaskEvent(
                    sequence_num=seq,
                    arrival_time_sec=round(current_time, 6),
                    inter_arrival_sec=round(dt, 6),
                    client_id=self.client_id,
                    task_type=t_type,
                    instantaneous_lambda=round(inst_lambda, 4),
                )
            )
        return events

    async def stream_events(
        self,
        max_tasks: int | None = 100,
        realtime_sleep: bool = True,
    ) -> AsyncIterator[GeneratedTaskEvent]:
        """Yield Poisson task events asynchronously, sleeping `dt` seconds between arrivals."""
        self._stop_requested = False
        seq = 0
        elapsed = 0.0
        while not self._stop_requested:
            if max_tasks is not None and seq >= max_tasks:
                break
            seq += 1
            inst_lambda = compute_scenario_lambda(
                self._lambda_rate,
                self.scenario,
                elapsed_sec=elapsed,
            )
            dt = sample_exponential_dt(inst_lambda, self._rng)
            if realtime_sleep and dt > 0:
                await asyncio.sleep(min(dt, 5.0))
            elapsed += dt
            t_type = sample_task_type(self.mix, self._rng)
            yield GeneratedTaskEvent(
                sequence_num=seq,
                arrival_time_sec=round(elapsed, 6),
                inter_arrival_sec=round(dt, 6),
                client_id=self.client_id,
                task_type=t_type,
                instantaneous_lambda=round(inst_lambda, 4),
            )

    async def run_against_target(
        self,
        target_url: str,
        max_tasks: int = 50,
        api_key: str | None = None,
        realtime_sleep: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ) -> TrafficRunSummary:
        """Send live Poisson traffic to `POST {target_url}/api/v1/tasks`."""
        summary = TrafficRunSummary(client_id=self.client_id)
        endpoint = f"{target_url.rstrip('/')}/api/v1/tasks"
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=10.0)
        start_wall = time.perf_counter()

        try:
            async for event in self.stream_events(
                max_tasks=max_tasks,
                realtime_sleep=realtime_sleep,
            ):
                summary.sent_count += 1
                summary.task_type_counts[event.task_type] = (
                    summary.task_type_counts.get(event.task_type, 0) + 1
                )
                try:
                    resp = await client.post(
                        endpoint,
                        json={
                            "client_id": event.client_id,
                            "task_type": event.task_type,
                        },
                        headers=headers,
                    )
                    if resp.status_code in (200, 201, 202):
                        summary.accepted_count += 1
                    elif resp.status_code == 429:
                        summary.backpressured_429_count += 1
                    else:
                        summary.error_count += 1
                except Exception:
                    summary.error_count += 1
        finally:
            if owns_client:
                await client.aclose()

        summary.elapsed_sec = round(max(0.001, time.perf_counter() - start_wall), 4)
        summary.effective_rate_per_sec = round(
            summary.sent_count / summary.elapsed_sec, 2
        )
        return summary


def superpose_seeded_streams(
    configs: list[ClientStreamConfig],
    total_duration_sec: float = 30.0,
) -> list[GeneratedTaskEvent]:
    """Generate and merge $M$ independent client Poisson streams into a single time-ordered trace.

    By the Superposition Theorem, merging independent Poisson streams with rates
    $\\lambda_1, \\dots, \\lambda_M$ produces a combined Poisson stream of rate $\\sum \\lambda_m$.
    """
    raw_events: list[GeneratedTaskEvent] = []
    for cfg in configs:
        gen = PoissonTrafficGenerator(
            client_id=cfg.client_id,
            lambda_rate=cfg.base_lambda,
            mix=cfg.mix,
            scenario=cfg.scenario,
            seed=cfg.seed,
        )
        trace = gen.generate_trace(
            max_tasks=cfg.max_tasks,
            total_duration_sec=total_duration_sec,
        )
        raw_events.extend(trace)

    raw_events.sort(key=lambda e: (e.arrival_time_sec, e.client_id, e.sequence_num))

    merged: list[GeneratedTaskEvent] = []
    prev_t = 0.0
    for idx, ev in enumerate(raw_events, start=1):
        dt = max(0.0, ev.arrival_time_sec - prev_t)
        prev_t = ev.arrival_time_sec
        merged.append(
            GeneratedTaskEvent(
                sequence_num=idx,
                arrival_time_sec=ev.arrival_time_sec,
                inter_arrival_sec=round(dt, 6),
                client_id=ev.client_id,
                task_type=ev.task_type,
                instantaneous_lambda=ev.instantaneous_lambda,
            )
        )
    return merged

