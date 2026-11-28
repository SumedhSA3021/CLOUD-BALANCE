"""Verification Script for Task A2: MILP In-Flight Counter.

In MILP mode, sends 20 concurrent requests to the live running controller
via inline MILP dispatch and reports the worker distribution across all 3 workers.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
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
    timeout = httpx.Timeout(30.0, connect=3.0)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        # 1. Verify cluster is ready
        try:
            r = await client.get("/api/v1/ready")
            print(f"[✓] Cluster ready check: {r.json()}")
        except (httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
            print(f"[!] Cannot reach cluster at {base_url}: {exc}")
            sys.exit(1)

        # 2. Reset solver metrics and set mode to ortools_milp
        await client.post("/api/v1/control/solver-metrics/reset", headers=admin_headers)
        sched_resp = await client.post(
            "/api/v1/control/scheduler",
            headers=admin_headers,
            json={"scheduler": "ortools_milp"},
        )
        print(f"[✓] Switched active scheduler to: {sched_resp.json()}")

        # 3. Fire 20 concurrent requests through unified POST /tasks
        print("\n[*] Firing 20 concurrent requests to /tasks in MILP mode...")

        async def send_task(idx: int) -> dict:
            cid = f"burst-client-{(idx % 3) + 1}"
            resp = await client.post(
                "/tasks",
                json={"client_id": cid, "task_type": "heavy", "size": 60000},
            )
            resp.raise_for_status()
            return resp.json()

        results = await asyncio.gather(*[send_task(i) for i in range(20)])
        solver_resp = await client.get("/api/v1/control/solver-metrics", headers=admin_headers)
        solver_call_count = solver_resp.json().get("solver_call_count", 0)
        print(
            f"[✓] Completed {len(results)} tasks through inline MILP "
            f"(solver_call_count={solver_call_count})."
        )

        # 4. Tally distribution
        counts = Counter(r["assigned_worker"] for r in results)

        print("\n" + "=" * 60)
        print(f"{'Worker ID':<15} | {'Task Count':<12} | {'Percentage':<10}")
        print("=" * 60)
        total = len(results) or 1
        for wid in ("worker-1", "worker-2", "worker-3"):
            c = counts.get(wid, 0)
            pct = (c / total) * 100.0
            print(f"{wid:<15} | {c:<12} | {pct:>6.1f}%")
        print("=" * 60)

        # 5. Verification results
        workers_used = len([w for w in ("worker-1", "worker-2", "worker-3") if counts.get(w, 0) > 0])
        print("\n[Verification Summary]")
        print(f"Total Concurrent Tasks : {len(results)}")
        print(f"Solver Call Count      : {solver_call_count} (Expected: > 0)")
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
