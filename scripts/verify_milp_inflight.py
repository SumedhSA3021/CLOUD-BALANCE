"""Verification Script for Task A2: MILP In-Flight Counter.

In MILP mode, sends 20 concurrent requests to the live running controller,
waits for micro-batch dispatch, and reports the worker distribution across all 3 workers.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
import httpx


async def run_check() -> None:
    base_url = "http://127.0.0.1:8000"
    timeout = httpx.Timeout(15.0, connect=3.0)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        # 1. Verify cluster is ready
        try:
            r = await client.get("/api/v1/ready")
            print(f"[✓] Cluster ready check: {r.json()}")
        except Exception as exc:
            print(f"[!] Cannot reach cluster at {base_url}: {exc}")
            sys.exit(1)

        # 2. Set mode to ortools_milp
        sched_resp = await client.post(
            "/api/v1/control/scheduler",
            json={"scheduler": "ortools_milp"},
        )
        print(f"[✓] Switched active scheduler to: {sched_resp.json()}")

        # 3. Fire 20 concurrent requests
        print("\n[*] Firing 20 concurrent requests in MILP mode...")
        task_types = ["CPU_INTENSIVE", "BALANCED_COMPUTE", "MEMORY_INTENSIVE", "LIGHTWEIGHT_QUERY"]
        submitted_task_ids: list[str] = []

        async def send_task(idx: int) -> str:
            ttype = task_types[idx % len(task_types)]
            cid = f"burst-client-{(idx % 4) + 1}"
            resp = await client.post(
                "/api/v1/tasks",
                json={"client_id": cid, "task_type": ttype},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["task_id"]

        submitted_task_ids = await asyncio.gather(*[send_task(i) for i in range(20)])
        print(f"[✓] Submitted {len(submitted_task_ids)} tasks into MILP micro-batch buffer.")

        # 4. Wait for micro-batch window (200ms) + dispatch to process
        print("[*] Waiting for batcher flush and dispatch completion...")
        await asyncio.sleep(1.2)

        # 5. Fetch recent assignments matching submitted task IDs
        recent_resp = await client.get("/api/v1/tasks/recent?limit=40")
        recent_assignments = recent_resp.json()
        target_set = set(submitted_task_ids)

        matched_assignments = [a for a in recent_assignments if a["task_id"] in target_set]

        # Retry once if still finishing
        if len(matched_assignments) < 20:
            await asyncio.sleep(1.0)
            recent_resp = await client.get("/api/v1/tasks/recent?limit=40")
            recent_assignments = recent_resp.json()
            matched_assignments = [a for a in recent_assignments if a["task_id"] in target_set]

        print(f"[✓] Retrieved {len(matched_assignments)} completed assignments.")

        # 6. Tally distribution
        counts = Counter(a["assigned_worker_id"] for a in matched_assignments)

        print("\n" + "=" * 60)
        print(f"{'Worker ID':<15} | {'Task Count':<12} | {'Percentage':<10}")
        print("=" * 60)
        total = len(matched_assignments) or 1
        for wid in ("worker-1", "worker-2", "worker-3"):
            c = counts.get(wid, 0)
            pct = (c / total) * 100.0
            print(f"{wid:<15} | {c:<12} | {pct:>6.1f}%")
        print("=" * 60)

        # 7. Verification results
        workers_used = len([w for w in ("worker-1", "worker-2", "worker-3") if counts.get(w, 0) > 0])
        print(f"\n[Verification Summary]")
        print(f"Total Concurrent Tasks : {len(matched_assignments)}")
        print(f"Worker Distribution    : {dict(counts)}")
        print(f"Workers Utilized       : {workers_used}/3")
        print(f"Anti-Piling Verified   : {'PASS [✓]' if workers_used == 3 else 'FAIL [✗]'}")

        if workers_used == 3:
            print("\n[SUCCESS] Task A2: MILP burst successfully distributed across all 3 workers!")
        else:
            print("\n[FAILURE] Tasks piled onto fewer than 3 workers!")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_check())
