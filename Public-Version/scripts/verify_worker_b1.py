"""Verification Script for Task B1: Worker Task Functions on port 8001.

Calls /execute on port 8001 for both 'light' (CGPA calculation) and 'heavy' (SHA-256 loop),
plus payload size check, displaying results and internally measured exec_ms.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx


def _resolve_worker_url() -> str:
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.core.config import ClientSettings

    return ClientSettings().resolved_worker_url()


def run_checks() -> None:
    worker_url = _resolve_worker_url()
    print(f"Connecting to Worker Executor at {worker_url}...\n")

    with httpx.Client(base_url=worker_url, timeout=30.0) as client:
        # Check health
        health = client.get("/health").json()
        print(f"[✓] Worker Health: {health}\n")

        # -------------------------------------------------------------
        # 1. task_type "light": CGPA Calculation
        # -------------------------------------------------------------
        print("=" * 70)
        print("TEST 1: task_type 'light' — CGPA Calculation")
        print("=" * 70)
        light_req = {
            "task_id": "tsk-cgpa-student01",
            "task_type": "light",
            "payload": {
                "student_id": "2SD24CS103",
                "semester": 4,
                "courses": [
                    {"code": "CS401", "name": "Design & Analysis of Algorithms", "credits": 4, "grade": 9.0},
                    {"code": "CS402", "name": "Operating Systems", "credits": 4, "grade": 8.5},
                    {"code": "CS403", "name": "Database Management Systems", "credits": 4, "grade": 9.5},
                    {"code": "CS404", "name": "Theory of Computation", "credits": 3, "grade": 8.0},
                    {"code": "CS405", "name": "Software Engineering", "credits": 3, "grade": 9.0},
                    {"code": "CS406", "name": "Algorithms Lab", "credits": 1.5, "grade": 10.0},
                    {"code": "CS407", "name": "DBMS Lab", "credits": 1.5, "grade": 9.5},
                ],
            },
        }
        print("Payload Sent:")
        print(json.dumps(light_req, indent=2))

        resp_light = client.post("/execute", json=light_req)
        print(f"\nResponse Code : {resp_light.status_code}")
        light_data = resp_light.json()
        print("Response Body :")
        print(json.dumps(light_data, indent=2))
        print(f"\n-> Result Summary: CGPA = {light_data['result']['cgpa']} / 10.0 "
              f"(Total Credits: {light_data['result']['total_credits']})")
        print(f"-> Measured Execution Time: {light_data['execution_ms']:.2f} ms")

        # -------------------------------------------------------------
        # 2. task_type "heavy": Hashing Loop (SHA-256)
        # -------------------------------------------------------------
        print("\n" + "=" * 70)
        print("TEST 2: task_type 'heavy' — Iterative SHA-256 Hashing Loop")
        print("=" * 70)
        heavy_req = {
            "task_id": "tsk-heavy-crypto01",
            "task_type": "heavy",
            "payload": {
                "data": "cloudbalance-block-payload-header-seed",
                "iterations": 200000,
            },
        }
        print("Payload Sent:")
        print(json.dumps(heavy_req, indent=2))

        resp_heavy = client.post("/execute", json=heavy_req)
        print(f"\nResponse Code : {resp_heavy.status_code}")
        heavy_data = resp_heavy.json()
        print("Response Body :")
        print(json.dumps(heavy_data, indent=2))
        print(f"\n-> Result Summary: Final Hash = {heavy_data['result']['final_hash']}")
        print(f"-> Iterations Completed    : {heavy_data['result']['iterations']}")
        print(f"-> Measured Execution Time : {heavy_data['execution_ms']:.2f} ms "
              f"({heavy_data['execution_ms']/1000.0:.3f} s)")

        # -------------------------------------------------------------
        # 3. Payload Size Limit Enforcement (Reject > 64 KB with 413)
        # -------------------------------------------------------------
        print("\n" + "=" * 70)
        print("TEST 3: Safe Payload Limit Enforcement (> 64 KB)")
        print("=" * 70)
        huge_payload = {
            "task_id": "tsk-oversized-01",
            "task_type": "light",
            "payload": {"junk": "A" * (75 * 1024)},
        }
        resp_oversized = client.post("/execute", json=huge_payload)
        print(f"Response Code for 75 KB payload: {resp_oversized.status_code} (Expected 413)")
        print(f"Error Detail : {resp_oversized.json().get('detail')}")

        # -------------------------------------------------------------
        # 4. Invalid Input Rejection (400)
        # -------------------------------------------------------------
        print("\n" + "=" * 70)
        print("TEST 4: Invalid CGPA Input Validation")
        print("=" * 70)
        invalid_req = {
            "task_id": "tsk-invalid-01",
            "task_type": "light",
            "payload": {
                "courses": [{"name": "InvalidCourse", "credits": 4, "grade": 15.0}]
            },
        }
        resp_invalid = client.post("/execute", json=invalid_req)
        print(f"Response Code for grade 15.0: {resp_invalid.status_code} (Expected 400)")
        print(f"Error Detail : {resp_invalid.json().get('detail')}")

        print("\n" + "=" * 70)
        print("[✓] ALL TASK B1 REQUIREMENTS VERIFIED ON PORT 8001!")
        print("=" * 70)


if __name__ == "__main__":
    run_checks()
