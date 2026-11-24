"""Built-in Deterministic Load Simulator for CloudBalance Automated Tests (Task D1).

Generates seeded Poisson workloads from simulated clients ('sim-1', 'sim-2', 'sim-3')
and dispatches them asynchronously through the exact same task contract pipeline.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import numpy as np

from app.core.logging import get_logger

logger = get_logger("core.simulator")


def build_deterministic_schedule(
    duration_s: float,
    lambda_rate: float,
    heavy_ratio: float,
    seed: int,
    client_no: int,
) -> list[tuple[float, str]]:
    """Build the full schedule BEFORE starting, deterministically from seed + client_no.

    Matches tools/load_client.py:
    - Exponential gaps with mean 1 / lambda_rate.
    - Heavy tasks with probability heavy_ratio.
    """
    rng = np.random.default_rng(seed + client_no)
    schedule: list[tuple[float, str]] = []
    curr_time = 0.0
    mean_gap = 1.0 / max(0.001, lambda_rate)

    while curr_time < duration_s:
        gap = float(rng.exponential(scale=mean_gap))
        curr_time += gap
        if curr_time >= duration_s:
            break
        is_heavy = float(rng.random()) < heavy_ratio
        task_type = "heavy" if is_heavy else "light"
        schedule.append((curr_time, task_type))

    return schedule


class AppProxyRequest:
    """Minimal request proxy carrying app.state for internal task dispatch."""

    def __init__(self, app: Any) -> None:
        if hasattr(app, "state"):
            self.app = app
        else:
            class _AppWrapper:
                def __init__(self, st: Any) -> None:
                    self.state = st
            self.app = _AppWrapper(app)


class InternalLoadSimulator:
    """Manages internal client worker loops (sim-1, sim-2, sim-3)."""

    def __init__(self) -> None:
        self._running: bool = False
        self._client_tasks: list[asyncio.Task[None]] = []
        self._dispatch_tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()
        self.counters: dict[str, int] = {"sent": 0, "ok": 0, "failed": 0}

    @property
    def is_running(self) -> bool:
        return self._running

    def get_counters(self) -> dict[str, int]:
        return dict(self.counters)

    def reset_counters(self) -> None:
        self.counters = {"sent": 0, "ok": 0, "failed": 0}

    async def start(
        self,
        app: Any,
        duration_s: float,
        lambda_per_client: float,
        heavy_ratio: float,
        seed: int,
        start_at: float,
        num_clients: int = 3,
        on_result: Callable[[str], None] | None = None,
    ) -> None:
        """Start N simulated client workers."""
        async with self._lock:
            if self._running:
                await self.stop()

            self._running = True
            self.reset_counters()
            self._client_tasks = []

            for i in range(1, num_clients + 1):
                client_id = f"sim-{i}"
                schedule = build_deterministic_schedule(
                    duration_s=duration_s,
                    lambda_rate=lambda_per_client,
                    heavy_ratio=heavy_ratio,
                    seed=seed,
                    client_no=i,
                )
                task = asyncio.create_task(
                    self._run_client_schedule(
                        app=app,
                        client_id=client_id,
                        schedule=schedule,
                        start_at=start_at,
                        duration_s=duration_s,
                        on_result=on_result,
                    ),
                    name=f"sim-client-{client_id}",
                )
                self._client_tasks.append(task)

            logger.info(
                "load_simulator_started",
                clients=num_clients,
                duration_s=duration_s,
                lambda_per_client=lambda_per_client,
                seed=seed,
            )

    async def stop(self) -> None:
        """Cancel all simulated clients and pending background dispatches."""
        async with self._lock:
            self._running = False
            for task in self._client_tasks:
                if not task.done():
                    task.cancel()
            self._client_tasks.clear()

            for d_task in list(self._dispatch_tasks):
                if not d_task.done():
                    d_task.cancel()
            self._dispatch_tasks.clear()

            logger.info("load_simulator_stopped", counters=self.counters)

    async def _run_client_schedule(
        self,
        app: Any,
        client_id: str,
        schedule: list[tuple[float, str]],
        start_at: float,
        duration_s: float,
        on_result: Callable[[str], None] | None = None,
    ) -> None:
        """Run the pre-built deterministic schedule for a single simulated client."""
        # 1. Wait until start_at
        now = time.time()
        wait_s = max(0.0, start_at - now)
        if wait_s > 0:
            await asyncio.sleep(wait_s)

        client_start_mono = time.monotonic()

        for offset_time, task_type in schedule:
            if not self._running:
                break

            target_mono = client_start_mono + offset_time
            sleep_gap = target_mono - time.monotonic()
            if sleep_gap > 0:
                await asyncio.sleep(sleep_gap)

            if not self._running or time.monotonic() - client_start_mono >= duration_s:
                break

            # Send task asynchronously without blocking next scheduled dispatch
            d_task = asyncio.create_task(
                self._dispatch_single_task(
                    app=app,
                    client_id=client_id,
                    task_type=task_type,
                    on_result=on_result,
                )
            )
            self._dispatch_tasks.add(d_task)
            d_task.add_done_callback(self._dispatch_tasks.discard)

    async def _dispatch_single_task(
        self,
        app: Any,
        client_id: str,
        task_type: str,
        on_result: Callable[[str], None] | None = None,
    ) -> None:
        """Execute task contract request and update counters."""
        from app.api.tasks import TaskContractRequest, execute_task_contract

        self.counters["sent"] += 1
        req = TaskContractRequest(
            client_id=client_id,
            task_type=task_type,
            sent_at=round(time.time(), 3),
            size=150000 if task_type == "heavy" else 4,
        )
        dummy_req = AppProxyRequest(app=app)

        try:
            resp = await execute_task_contract(req, dummy_req)  # type: ignore[arg-type]
            res_dict = resp.result if isinstance(resp.result, dict) else {}
            st = str(res_dict.get("status", "")).lower()

            if "503" in st or "rejected" in st:
                self.counters["failed"] += 1
                if on_result:
                    on_result("rejected_503")
            elif "timeout" in st or "error" in st:
                self.counters["failed"] += 1
                if on_result:
                    on_result("timeout")
            else:
                self.counters["ok"] += 1
                if on_result:
                    on_result("ok")
        except Exception as exc:
            self.counters["failed"] += 1
            if on_result:
                on_result("error")
            logger.warning("sim_task_dispatch_failed", client_id=client_id, error=str(exc))


simulator_manager = InternalLoadSimulator()
