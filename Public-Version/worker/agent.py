"""Worker Telemetry Agent sampling psutil every 2s and reporting to Controller."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
from datetime import UTC, datetime
from typing import Any

import httpx
import psutil

from worker.executor import (
    DEFAULT_AGENT_INTERVAL_SEC,
    WorkerRuntimeState,
    load_worker_settings,
)

_DEFAULT_WORKER_SETTINGS = load_worker_settings()


def _get_os_load_avg(fallback_cpu_pct: float) -> float:
    """Return 1-minute OS load average, with safe fallback on Windows."""
    getloadavg_fn: Any = getattr(os, "getloadavg", None)
    if callable(getloadavg_fn):
        try:
            load_vals: Any = getloadavg_fn()
            return round(float(load_vals[0]), 2)
        except OSError:
            pass
    return round(fallback_cpu_pct / 25.0, 2)


def sample_worker_telemetry(
    worker_id: str,
    ip_address: str,
    port: int = int(_DEFAULT_WORKER_SETTINGS.worker_port),
    runtime_state: WorkerRuntimeState | None = None,
    virtual_profile: bool = True,
) -> dict[str, Any]:
    """Sample real OS utilization via psutil and combine with worker runtime state.

    When `virtual_profile` is True (default for multi-worker local mode where 3 workers
    share one host kernel), blends real `psutil` readings with the worker's own
    active task CPU/RAM allocation so each worker VM exhibits realistic independent telemetry.
    """
    raw_cpu = float(psutil.cpu_percent(interval=None))
    vm = psutil.virtual_memory()
    raw_mem_total_mb = float(vm.total) / (1024.0 * 1024.0)
    raw_mem_used_mb = float(vm.used) / (1024.0 * 1024.0)

    if runtime_state is not None and virtual_profile:
        total_mem_mb = runtime_state.total_mem_mb
        # Blend 20% of real host CPU jitter with the worker's own baseline + active task load
        cpu_pct = min(
            100.0,
            round(
                runtime_state.base_cpu_pct
                + (raw_cpu * 0.15)
                + runtime_state.active_cpu_demand_pct,
                2,
            ),
        )
        mem_used_mb = min(
            total_mem_mb,
            round(runtime_state.base_mem_mb + runtime_state.active_mem_demand_mb, 2),
        )
        mem_pct = min(100.0, round((mem_used_mb / total_mem_mb) * 100.0, 2))
        active_tasks = runtime_state.active_task_count
    else:
        total_mem_mb = round(raw_mem_total_mb, 2)
        mem_used_mb = round(raw_mem_used_mb, 2)
        cpu_pct = min(100.0, max(0.0, round(raw_cpu, 2)))
        mem_pct = min(100.0, max(0.0, round(float(vm.percent), 2)))
        active_tasks = runtime_state.active_task_count if runtime_state else 0

    load_1m = _get_os_load_avg(cpu_pct)

    return {
        "worker_id": worker_id,
        "ip_address": ip_address,
        "port": port,
        "timestamp": datetime.now(UTC).isoformat(),
        "cpu_percent": cpu_pct,
        "memory_total_mb": round(total_mem_mb, 2),
        "memory_used_mb": round(mem_used_mb, 2),
        "memory_percent": mem_pct,
        "load_avg_1m": load_1m,
        "active_task_count": active_tasks,
        "queue_length": runtime_state.current_queue_length if runtime_state else 0,
    }


class WorkerTelemetryAgent:
    """Periodic telemetry reporter sending psutil snapshots to Controller every 2s."""

    def __init__(
        self,
        worker_id: str,
        ip_address: str,
        port: int = int(_DEFAULT_WORKER_SETTINGS.worker_port),
        controller_url: str = str(_DEFAULT_WORKER_SETTINGS.controller_url),
        interval_sec: float = DEFAULT_AGENT_INTERVAL_SEC,
        api_key: str | None = None,
        worker_secret: str | None = None,
        runtime_state: WorkerRuntimeState | None = None,
        virtual_profile: bool = True,
    ) -> None:
        ws = load_worker_settings()
        self.worker_id = worker_id
        self.ip_address = ip_address
        self.port = port
        self.controller_url = controller_url.rstrip("/")
        self.interval_sec = interval_sec
        self.api_key = api_key if api_key is not None else ws.api_key
        resolved_secret = worker_secret if worker_secret is not None else ws.worker_secret
        self.worker_secret = resolved_secret.strip() if resolved_secret else None
        self.runtime_state = runtime_state
        self.virtual_profile = virtual_profile
        self._running = False

    async def send_once(self, client: httpx.AsyncClient) -> bool:
        """Sample telemetry once and POST to Controller `/api/v1/telemetry`."""
        payload = sample_worker_telemetry(
            worker_id=self.worker_id,
            ip_address=self.ip_address,
            port=self.port,
            runtime_state=self.runtime_state,
            virtual_profile=self.virtual_profile,
        )
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.worker_secret:
            headers["X-Worker-Secret"] = self.worker_secret

        resp = await client.post(
            f"{self.controller_url}/api/v1/telemetry",
            json=payload,
            headers=headers,
        )
        return resp.status_code in (200, 201, 202)

    async def run_forever(self, max_iterations: int | None = None) -> None:
        """Continuously sample and post telemetry every `interval_sec` seconds."""
        self._running = True
        iterations = 0
        async with httpx.AsyncClient(timeout=5.0) as client:
            while self._running:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1
                with contextlib.suppress(httpx.HTTPError, OSError, TimeoutError):
                    await self.send_once(client)
                await asyncio.sleep(self.interval_sec)

    def stop(self) -> None:
        """Stop the telemetry reporting loop."""
        self._running = False


def main() -> None:
    """CLI entrypoint for standalone worker telemetry agent."""
    ws = load_worker_settings()
    parser = argparse.ArgumentParser(description="CloudBalance Worker Telemetry Agent")
    parser.add_argument("--worker-id", default=ws.worker_id)
    parser.add_argument("--ip-address", default=ws.worker_ip)
    parser.add_argument("--port", type=int, default=int(ws.worker_port))
    parser.add_argument(
        "--controller-url",
        default=ws.controller_url,
    )
    parser.add_argument("--interval", type=float, default=DEFAULT_AGENT_INTERVAL_SEC)
    parser.add_argument("--api-key", default=ws.api_key)
    parser.add_argument(
        "--worker-secret",
        default=ws.worker_secret,
    )
    args = parser.parse_args()

    agent = WorkerTelemetryAgent(
        worker_id=args.worker_id,
        ip_address=args.ip_address,
        port=args.port,
        controller_url=args.controller_url,
        interval_sec=args.interval,
        api_key=args.api_key,
        worker_secret=args.worker_secret,
    )
    asyncio.run(agent.run_forever())


if __name__ == "__main__":
    main()

