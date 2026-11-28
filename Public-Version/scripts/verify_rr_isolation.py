"""Verification Script for Task A1: Round Robin Isolation.

Fires ~30 concurrent requests to the local controller in round_robin mode,
prints the assigned workers sorted by dispatch_seq, confirms the w1, w2, w3 pattern,
and validates solver_call_count == 0.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx


def _load_client_settings() -> tuple[str, str]:
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.core.config import ClientSettings

    cfg = ClientSettings()
    return cfg.controller_url, cfg.admin_token


async def run_check() -> None:
    base_url, admin_token = _load_client_settings()
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    timeout = httpx.Timeout(10.0, connect=3.0)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        # 1. Verify controller is reachable
        try:
            ready_resp = await client.get("/api/v1/ready")
            ready_data = ready_resp.json()
            print(f"[✓] Controller is ready: {ready_data}")
        except (httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
            print(f"[!] Controller not reachable at {base_url}: {exc}")
            sys.exit(1)

        # 2. Reset solver call count
        reset_resp = await client.post("/api/v1/control/solver-metrics/reset", headers=admin_headers)
        print(f"[✓] Reset solver metrics: {reset_resp.json()}")

        # 3. Switch active scheduler to round_robin
        sched_resp = await client.post(
            "/api/v1/control/scheduler",
            headers=admin_headers,
            json={"scheduler": "round_robin"},
        )
        print(f"[✓] Set active scheduler: {sched_resp.json()}")

        # 4. Fire 30 concurrent requests to unified POST /tasks
        print("\n[*] Firing 30 concurrent task requests to /tasks...")
        task_types = [
            "light",
            "heavy",
        ]

        async def send_task(idx: int) -> dict:
            ttype = task_types[idx % len(task_types)]
            cid = f"client-laptop-{(idx % 3) + 1}"
            payload = {"client_id": cid, "task_type": ttype}
            if ttype == "heavy":
                payload["size"] = 20000
            resp = await client.post("/tasks", json=payload)
            resp.raise_for_status()
            data = resp.json()
            data["_client_id"] = cid
            data["_task_type"] = ttype
            return data

        results = await asyncio.gather(*[send_task(i) for i in range(30)])

        # 5. Check solver call count
        solver_resp = await client.get("/api/v1/control/solver-metrics", headers=admin_headers)
        solver_call_count = solver_resp.json().get("solver_call_count", -1)

        # 6. Sort results by dispatch_seq
        sorted_results = sorted(results, key=lambda r: int(r.get("dispatch_seq") or 0))

        # 7. Print formatted table
        print("\n" + "=" * 90)
        print(f"{'Seq':<5} | {'Client ID':<16} | {'Type':<6} | {'Worker':<10} | {'Scheduler':<12} | {'Total ms'}")
        print("=" * 90)

        pattern_matches = True
        expected_worker_order = ["worker-1", "worker-2", "worker-3"]

        for r in sorted_results:
            seq = r.get("dispatch_seq")
            client_id = r.get("_client_id", "N/A")
            ttype = r.get("_task_type", "N/A")
            worker = r.get("assigned_worker", "N/A")
            scheduler_used = r.get("scheduler_used", "N/A")
            total_ms = r.get("total_ms", 0.0)

            # Check cyclic pattern: index relative to sequence number
            if isinstance(seq, int):
                expected_worker = expected_worker_order[(seq - 1) % 3]
                if worker != expected_worker or scheduler_used != "round_robin":
                    pattern_matches = False
            else:
                pattern_matches = False

            print(
                f"{seq!s:<5} | {client_id:<16} | {ttype:<6} | {worker:<10} | {scheduler_used:<12} | {total_ms}"
            )

        print("=" * 90)
        print("\n[Verification Summary]")
        print(f"Total Concurrent Requests : {len(sorted_results)}")
        print(f"Solver Call Count (RR)    : {solver_call_count} (Expected: 0)")
        print(f"Strict w1->w2->w3 Cycling : {'PASS [✓]' if pattern_matches else 'FAIL [✗]'}")
        print(f"Solver Never Called (RR)  : {'PASS [✓]' if solver_call_count == 0 else 'FAIL [✗]'}")

        if pattern_matches and solver_call_count == 0:
            print("\n[SUCCESS] Round Robin isolation fix verified completely!")
        else:
            print("\n[FAILURE] Verification checks failed!")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_check())
