"""Verification Script for Task A1: Round Robin Isolation.

Fires ~30 concurrent requests to the local controller in round_robin mode,
prints the assigned workers sorted by dispatch_seq, confirms the w1, w2, w3 pattern,
and validates solver_call_count == 0.
"""

from __future__ import annotations

import asyncio
import sys
import httpx


async def run_check() -> None:
    base_url = "http://127.0.0.1:8000"
    timeout = httpx.Timeout(10.0, connect=3.0)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        # 1. Verify controller is reachable
        try:
            ready_resp = await client.get("/api/v1/ready")
            ready_data = ready_resp.json()
            print(f"[✓] Controller is ready: {ready_data}")
        except Exception as exc:
            print(f"[!] Controller not reachable at {base_url}: {exc}")
            sys.exit(1)

        # 2. Reset solver call count
        reset_resp = await client.post("/api/v1/control/solver-metrics/reset")
        print(f"[✓] Reset solver metrics: {reset_resp.json()}")

        # 3. Switch active scheduler to round_robin
        sched_resp = await client.post(
            "/api/v1/control/scheduler",
            json={"scheduler": "round_robin"},
        )
        print(f"[✓] Set active scheduler: {sched_resp.json()}")

        # 4. Fire 30 concurrent requests
        print("\n[*] Firing 30 concurrent task requests to /api/v1/tasks...")
        task_types = [
            "LIGHTWEIGHT_QUERY",
            "BALANCED_COMPUTE",
            "CPU_INTENSIVE",
            "MEMORY_INTENSIVE",
        ]

        async def send_task(idx: int) -> dict:
            ttype = task_types[idx % len(task_types)]
            cid = f"client-laptop-{(idx % 4) + 1}"
            resp = await client.post(
                "/api/v1/tasks",
                json={"client_id": cid, "task_type": ttype},
            )
            resp.raise_for_status()
            return resp.json()

        results = await asyncio.gather(*[send_task(i) for i in range(30)])

        # 5. Check solver call count
        solver_resp = await client.get("/api/v1/control/solver-metrics")
        solver_call_count = solver_resp.json().get("solver_call_count", -1)

        # 6. Sort results by dispatch_seq
        sorted_results = sorted(results, key=lambda r: r.get("dispatch_seq", 0))

        # 7. Print formatted table
        print("\n" + "=" * 90)
        print(f"{'Seq':<5} | {'Task ID':<18} | {'Client ID':<18} | {'Worker':<12} | {'Mode':<12} | {'Accepted'}")
        print("=" * 90)

        pattern_matches = True
        expected_worker_order = ["worker-1", "worker-2", "worker-3"]
        start_seq = sorted_results[0].get("dispatch_seq", 1)

        for i, r in enumerate(sorted_results):
            seq = r.get("dispatch_seq")
            task_id = r.get("task_id", "N/A")
            client_id = r.get("client_id", "N/A")
            worker = r.get("assigned_worker_id", "N/A")
            mode = r.get("mode", "N/A")
            accepted = r.get("accepted", False)

            # Check cyclic pattern: index relative to first sequence
            expected_worker = expected_worker_order[(seq - 1) % 3]
            if worker != expected_worker:
                pattern_matches = False

            print(f"{seq:<5} | {task_id:<18} | {client_id:<18} | {worker:<12} | {mode:<12} | {accepted}")

        print("=" * 90)
        print(f"\n[Verification Summary]")
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
