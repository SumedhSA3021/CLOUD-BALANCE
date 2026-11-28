"""End-to-End Final Acceptance Suite (Checks A-L) for CloudBalance.

Runs against a live cluster at CB_BASE_URL (1 round x 30s milp, then 30s round_robin)
with 3 script-driven (not browser) Poisson clients:
  - client-1: heavy @ 3.0 req/s
  - client-2: light @ 3.0 req/s
  - client-3: heavy @ 3.0 req/s

Prints a structured PASS/FAIL table (A-L) with raw evidence and never prints secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import ClientSettings
from app.core.logger import TEST_LOG_COLUMNS, TEST_SUMMARY_COLUMNS

DURATION_S = 30.0
RATE_PER_CLIENT = 3.0
SEED = 42
CLIENT_SPECS: tuple[tuple[int, str, str, float], ...] = (
    (1, "client-1", "heavy", RATE_PER_CLIENT),
    (2, "client-2", "light", RATE_PER_CLIENT),
    (3, "client-3", "heavy", RATE_PER_CLIENT),
)
KNOWN_LEGACY_SECRETS = {
    "cb-admin-secret-2026",
    "cb-dev-api-key-2026",
    "cb-redis-local-pass",
}


@dataclass
class ClientResult:
    client_id: str
    task_type: str
    declared_rate: float
    scheduled: int
    sent: int
    ok: int
    failed: int


@dataclass
class ModeRunResult:
    mode: str
    test_id: str
    solver_call_count: int
    clients: dict[str, ClientResult]


@dataclass
class CheckResult:
    key: str
    name: str
    passed: bool
    evidence: str
    observation: bool = False


def _build_task_payload(
    client_id: str,
    task_type: str,
    client_rate: float | None = None,
    client_task_type: str | None = None,
) -> dict[str, Any]:
    if task_type == "heavy":
        payload: dict[str, Any] = {
            "client_id": client_id,
            "task_type": "heavy",
            "size": 150000,
            "sent_at": time.time(),
            "payload": {
                "data": "cloudbalance-heavy-workload-2026",
                "iterations": 150000,
            },
        }
    else:
        payload = {
            "client_id": client_id,
            "task_type": "light",
            "size": 4,
            "sent_at": time.time(),
            "payload": {
                "courses": [
                    {"name": "Cloud Computing", "credits": 4, "grade": 9.0},
                    {"name": "Algorithms", "credits": 4, "grade": 8.5},
                    {"name": "Storage Systems", "credits": 3, "grade": 9.0},
                ]
            },
        }
    if client_rate is not None:
        payload["client_rate"] = client_rate
    if client_task_type is not None:
        payload["client_task_type"] = client_task_type
    return payload


def _build_fixed_schedule(client_no: int, duration_s: float, rate: float, seed: int) -> list[float]:
    """Build deterministic exponential arrival offsets strictly inside [0, duration_s - 0.25)."""
    rng = np.random.default_rng(seed + client_no)
    offsets: list[float] = []
    t_curr = 0.0
    mean_gap = 1.0 / rate
    cutoff = max(1.0, duration_s - 0.25)
    while True:
        t_curr += float(rng.exponential(scale=mean_gap))
        if t_curr >= cutoff:
            break
        offsets.append(t_curr)
    return offsets


async def _wait_for_state(
    client: httpx.AsyncClient,
    target_states: tuple[str, ...],
    timeout_s: float = 45.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = await client.get("/test/status", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            if str(data.get("state", "")).lower() in target_states:
                return data
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for /test/status in {target_states}")


async def _run_script_client(
    client: httpx.AsyncClient,
    client_id: str,
    task_type: str,
    rate: float,
    offsets: list[float],
    start_at: float,
    duration_s: float,
    test_id: str,
) -> ClientResult:
    delay = start_at - time.time() + 0.05
    if delay > 0:
        await asyncio.sleep(delay)

    start_mono = time.monotonic()
    counter = {"ok": 0, "failed": 0}
    in_flight: list[asyncio.Task[None]] = []
    stop_event = asyncio.Event()

    async def _watch_status() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(0.5)
            with contextlib.suppress(httpx.HTTPError, OSError, TimeoutError):
                st = await client.get("/test/status", timeout=3.0)
                if st.status_code == 200:
                    d = st.json()
                    if d.get("test_id") != test_id or str(d.get("state")).lower() not in ("armed", "running"):
                        stop_event.set()
                        return

    async def _send_one() -> None:
        body = _build_task_payload(
            client_id=client_id,
            task_type=task_type,
            client_rate=rate,
            client_task_type=task_type,
        )
        try:
            r = await client.post("/tasks", json=body, timeout=25.0)
            if r.status_code == 200:
                counter["ok"] += 1
            else:
                counter["failed"] += 1
        except (httpx.HTTPError, OSError, TimeoutError, ValueError):
            counter["failed"] += 1

    watcher = asyncio.create_task(_watch_status())
    try:
        for offset in offsets:
            elapsed = time.monotonic() - start_mono
            if elapsed >= duration_s - 0.1 or stop_event.is_set():
                break
            wait_s = (start_mono + offset) - time.monotonic()
            if wait_s > 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait_s)
                    break
                except TimeoutError:
                    pass
            if (time.monotonic() - start_mono) >= duration_s - 0.1 or stop_event.is_set():
                break
            in_flight.append(asyncio.create_task(_send_one()))
    finally:
        stop_event.set()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher

    if in_flight:
        _done, pending = await asyncio.wait(in_flight, timeout=20.0)
        for p in pending:
            p.cancel()
            counter["failed"] += 1

    return ClientResult(
        client_id=client_id,
        task_type=task_type,
        declared_rate=rate,
        scheduled=len(offsets),
        sent=len(in_flight),
        ok=counter["ok"],
        failed=counter["failed"],
    )


async def _execute_mode_run(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    mode: str,
    schedules: dict[str, list[float]],
) -> tuple[ModeRunResult, tuple[int, int] | None]:
    await _wait_for_state(client, ("idle",), timeout_s=30.0)

    reset_metrics = await client.post("/api/v1/control/solver-metrics/reset", headers=admin_headers)
    if reset_metrics.status_code != 200:
        raise RuntimeError(f"Failed solver-metrics reset: {reset_metrics.status_code} {reset_metrics.text}")

    start_resp = await client.post(
        "/admin/test/start",
        headers=admin_headers,
        json={
            "mode": mode,
            "duration_s": DURATION_S,
            "lambda_per_client": RATE_PER_CLIENT,
            "heavy_ratio": 0.67,
            "seed": SEED,
            "load_source": "external",
        },
    )
    if start_resp.status_code != 200:
        raise RuntimeError(f"Failed /admin/test/start ({mode}): {start_resp.status_code} {start_resp.text}")

    armed_info = start_resp.json()
    test_id = str(armed_info["test_id"])
    start_at = float(armed_info["start_at"])
    print(f"[script-driven, not browser] Armed mode={mode}, test_id={test_id}, start_at={start_at}")

    lock_statuses: tuple[int, int] | None = None

    async def _probe_mode_lock() -> tuple[int, int]:
        await _wait_for_state(client, ("running",), timeout_s=15.0)
        r_switch = await client.post(
            "/api/v1/control/scheduler",
            headers=admin_headers,
            json={"scheduler": "round_robin" if mode == "milp" else "ortools_milp"},
        )
        r_second = await client.post(
            "/admin/test/start",
            headers=admin_headers,
            json={
                "mode": "round_robin",
                "duration_s": 10.0,
                "lambda_per_client": 1.0,
                "heavy_ratio": 0.5,
                "seed": SEED,
                "load_source": "external",
            },
        )
        return r_switch.status_code, r_second.status_code

    client_coros = [
        _run_script_client(
            client=client,
            client_id=cid,
            task_type=ttype,
            rate=rate,
            offsets=schedules[cid],
            start_at=start_at,
            duration_s=DURATION_S,
            test_id=test_id,
        )
        for _no, cid, ttype, rate in CLIENT_SPECS
    ]

    if mode == "milp":
        *client_results, lock_statuses = await asyncio.gather(*client_coros, _probe_mode_lock())
    else:
        client_results = list(await asyncio.gather(*client_coros))

    await _wait_for_state(client, ("idle",), timeout_s=30.0)
    await asyncio.sleep(0.5)  # allow CSV summary flush

    sm_resp = await client.get("/api/v1/control/solver-metrics", headers=admin_headers)
    if sm_resp.status_code != 200:
        raise RuntimeError(f"Failed solver-metrics read: {sm_resp.status_code}")
    solver_calls = int(sm_resp.json().get("solver_call_count", -1))

    res_map = {cr.client_id: cr for cr in client_results}
    for cid, cr in res_map.items():
        print(
            f"  [{mode}] [script-driven, not browser] {cid} ({cr.task_type} @ {cr.declared_rate}/s): "
            f"sent={cr.sent}, ok={cr.ok}, failed={cr.failed}"
        )
    return ModeRunResult(mode=mode, test_id=test_id, solver_call_count=solver_calls, clients=res_map), lock_statuses


def _strip_js_ts_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"//.*", "", text)


def _is_known_numeric_false_positive(rel_path: str, snippet: str) -> str | None:
    norm = rel_path.replace("\\", "/")
    if norm == "frontend/src/__tests__/App.test.tsx" and "port: 8001" in snippet:
        return "test_mock_port_8001"
    if norm == "frontend/src/hooks/useWebSocket.ts" and "Math.min(8000" in snippet:
        return "ws_retry_delay_8000ms"
    if norm.startswith("frontend/dist/assets/index-") and norm.endswith(".js") and '"8000"' in snippet:
        return "css_named_color_8000"
    return None


def _check_j_static_and_served(client: httpx.Client) -> CheckResult:
    host_or_port_pattern = re.compile(
        r"(localhost|127\.0\.0\.1|0\.0\.0\.0|:(?:8000|8001|8002|8003|5173)\b|"
        r"port\s*[:=]\s*(?:8000|8001|8002|8003|5173)\b)"
    )
    raw_num_pattern = re.compile(r"\b(?:8000|8001|8002|8003|5173)\b")

    non_test_src_hosts: list[str] = []
    dist_hosts: list[str] = []
    unexpected_num_hits: list[str] = []
    expected_false_positives: list[str] = []

    for base_rel in ("frontend/src", "frontend/dist"):
        base = ROOT_DIR / base_rel
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in (".ts", ".tsx", ".js", ".jsx", ".html", ".css"):
                continue
            rel = str(path.relative_to(ROOT_DIR))
            raw = path.read_text(encoding="utf-8", errors="ignore")
            is_test = "__tests__" in path.parts or ".test." in path.name
            scan_txt = _strip_js_ts_comments(raw) if is_test else raw

            for m in host_or_port_pattern.finditer(scan_txt):
                snippet = scan_txt[max(0, m.start() - 25) : min(len(scan_txt), m.end() + 25)].replace("\n", " ")
                entry = f"{rel}@{m.start()}: {snippet!r}"
                if base_rel == "frontend/dist":
                    fp_tag = _is_known_numeric_false_positive(rel, snippet)
                    if fp_tag:
                        expected_false_positives.append(f"{fp_tag}:{entry}")
                    else:
                        dist_hosts.append(entry)
                elif not is_test:
                    non_test_src_hosts.append(entry)
                else:
                    fp_tag = _is_known_numeric_false_positive(rel, snippet)
                    if fp_tag:
                        expected_false_positives.append(f"{fp_tag}:{entry}")
                    else:
                        non_test_src_hosts.append(entry)

            for m in raw_num_pattern.finditer(scan_txt):
                snippet = scan_txt[max(0, m.start() - 25) : min(len(scan_txt), m.end() + 25)].replace("\n", " ")
                entry = f"{rel}@{m.start()}: {snippet!r}"
                fp_tag = _is_known_numeric_false_positive(rel, snippet)
                if fp_tag:
                    tagged = f"{fp_tag}:{entry}"
                    if tagged not in expected_false_positives:
                        expected_false_positives.append(tagged)
                else:
                    unexpected_num_hits.append(entry)

    # Inspect served HTML + referenced JS bundles from / and /client
    html_pages: dict[str, str] = {}
    bundle_paths: set[str] = set()
    for route in ("/", "/client"):
        resp = client.get(route)
        html_pages[route] = f"{resp.status_code} ({len(resp.text)}B)"
        for m in re.finditer(r'src="(/assets/[^"]+\.js)"', resp.text):
            bundle_paths.add(m.group(1))

    forbidden_ui_tokens = ("/ops", "/benchmark", "/admin", "ADMIN_TOKEN", "Admin Token", "test_log.csv", "test_summary.csv")
    html_forbidden: list[str] = []
    for route in ("/", "/client"):
        body = client.get(route).text
        for tok in forbidden_ui_tokens:
            if tok in body:
                html_forbidden.append(f"{route}:{tok}")

    page_src_forbidden: list[str] = []
    for page_file in (
        ROOT_DIR / "frontend/src/pages/PublicTasksPage.tsx",
        ROOT_DIR / "frontend/src/pages/ClientLoadPage.tsx",
    ):
        clean_src = _strip_js_ts_comments(page_file.read_text(encoding="utf-8"))
        for tok in forbidden_ui_tokens + ("download", "type=\"password\"", "token"):
            if tok.lower() in clean_src.lower():
                page_src_forbidden.append(f"{page_file.name}:{tok}")

    bundle_status: dict[str, int] = {}
    bundle_spa_strings: dict[str, int] = {}
    for bp in sorted(bundle_paths):
        b_resp = client.get(bp)
        bundle_status[bp] = b_resp.status_code
        js_text = b_resp.text
        for tok in ("/ops", "/benchmark", "ADMIN_TOKEN", "Admin Token", "test_log.csv", "test_summary.csv"):
            c = js_text.count(tok)
            if c > 0:
                bundle_spa_strings[f"{bp}:{tok}"] = c

    passed = (
        all(html_pages[r].startswith("200 ") for r in ("/", "/client"))
        and bool(bundle_status)
        and all(code == 200 for code in bundle_status.values())
        and len(non_test_src_hosts) == 0
        and len(dist_hosts) == 0
        and len(unexpected_num_hits) == 0
        and len(html_forbidden) == 0
        and len(page_src_forbidden) == 0
    )
    evidence = (
        f"non_test_src_host_or_port={non_test_src_hosts}; dist_host_or_port={dist_hosts}; "
        f"unexpected_numeric={unexpected_num_hits}; expected_false_positives={expected_false_positives}; "
        f"html={html_pages}, html_forbidden={html_forbidden}; page_components_forbidden={page_src_forbidden}; "
        f"single_spa_bundle_expected_routes={bundle_spa_strings}"
    )
    return CheckResult(key="J", name="Static / & /client + frontend grep", passed=passed, evidence=evidence)


def _check_k_secrets() -> CheckResult:
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return CheckResult(key="K", name=".env secrets >=32 chars & not in git", passed=False, evidence=".env missing")

    env_vals: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, v = stripped.split("=", 1)
            env_vals[k.strip()] = v.strip().strip('"').strip("'")

    arch_text = ""
    arch_path = ROOT_DIR / "archive/backend.env"
    if arch_path.exists():
        arch_text = arch_path.read_text(encoding="utf-8", errors="ignore")

    details: list[str] = []
    all_ok = True
    for name in ("ADMIN_TOKEN", "WORKER_SECRET"):
        val = env_vals.get(name, "")
        len_ok = len(val) >= 32
        in_git = False
        if val:
            git_out = subprocess.check_output(
                ["git", "log", "--all", "--format=%H", "-S", val],
                cwd=str(ROOT_DIR),
                text=True,
                errors="ignore",
            ).strip()
            in_git = bool(git_out)
        in_arch = bool(val) and (val in arch_text)
        known_default = val in KNOWN_LEGACY_SECRETS
        ok = bool(val) and len_ok and not in_git and not in_arch and not known_default
        if not ok:
            all_ok = False
        details.append(
            f"{name}: present={bool(val)}, len={len(val)} (>=32:{len_ok}), in_git={in_git}, "
            f"in_archive_env={in_arch}, legacy={known_default}"
        )
    return CheckResult(key="K", name=".env secrets >=32 chars & not in git", passed=all_ok, evidence="; ".join(details))


async def _run_acceptance(base_url: str, admin_token: str) -> list[CheckResult]:
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    schedules = {cid: _build_fixed_schedule(no, DURATION_S, rate, SEED) for no, cid, _t, rate in CLIENT_SPECS}

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(base_url=base_url, limits=limits) as aclient:
        hz = await aclient.get("/healthz", timeout=5.0)
        rd = await aclient.get("/ready", timeout=5.0)
        if hz.status_code != 200 or rd.status_code != 200:
            raise RuntimeError(f"Controller not ready: /healthz={hz.status_code}, /ready={rd.status_code}")
        ready_json = rd.json()
        print(f"Cluster ready at {base_url}: {ready_json}")

        rst = await aclient.post("/admin/stats/reset", headers=admin_headers, timeout=10.0)
        if rst.status_code != 200:
            raise RuntimeError(f"POST /admin/stats/reset failed: {rst.status_code} {rst.text}")

        milp_run, lock_probe = await _execute_mode_run(aclient, admin_headers, "milp", schedules)
        print("Cooling down 10s between milp and round_robin runs...")
        await asyncio.sleep(10.0)
        rr_run, _ = await _execute_mode_run(aclient, admin_headers, "round_robin", schedules)

        pre_log_text = (await aclient.get("/admin/stats/download?file=test_log", headers=admin_headers)).text
        pre_log_count = len(list(csv.DictReader(io.StringIO(pre_log_text))))

        # Check H: Auth / Public probes
        auth_results: dict[str, int] = {}
        async with httpx.AsyncClient(base_url=base_url) as anon:
            for path in (
                "/api/v1/telemetry/workers",
                "/api/v1/control/snapshot",
                "/admin/stats/summary",
                "/api/v1/telemetry/redis",
                "/api/v1/benchmark/runs",
                "/healthz",
                "/test/status",
                "/",
                "/client",
            ):
                auth_results[path] = (await anon.get(path, timeout=5.0)).status_code

            # Check I: Public POST /tasks outside active test with client_id="web" (no client_rate/client_task_type)
            web_statuses: list[int] = []
            web_workers: list[str] = []
            for tt in ("light", "heavy"):
                r = await anon.post("/tasks", json=_build_task_payload("web", tt), timeout=20.0)
                web_statuses.append(r.status_code)
                if r.status_code == 200:
                    web_workers.append(str(r.json().get("assigned_worker", "")))

        await asyncio.sleep(0.5)
        log_csv_text = (await aclient.get("/admin/stats/download?file=test_log", headers=admin_headers)).text
        sum_csv_text = (await aclient.get("/admin/stats/download?file=test_summary", headers=admin_headers)).text

    print("\n--- TEST SUMMARY CSV ---")
    print(sum_csv_text.strip())

    # Parse CSV artifacts returned by the running controller
    log_reader = csv.reader(io.StringIO(log_csv_text))
    log_header = next(log_reader, [])
    log_dict_rows = list(csv.DictReader(io.StringIO(log_csv_text)))

    sum_reader = csv.reader(io.StringIO(sum_csv_text))
    sum_header = next(sum_reader, [])
    sum_dict_rows = list(csv.DictReader(io.StringIO(sum_csv_text)))

    sum_by_id = {r["test_id"]: r for r in sum_dict_rows}
    logs_by_id: dict[str, list[dict[str, str]]] = {}
    for row in log_dict_rows:
        logs_by_id.setdefault(row["test_id"], []).append(row)

    results: list[CheckResult] = []

    # Check A
    a_ok = True
    a_parts: list[str] = []
    for run in (milp_run, rr_run):
        srow = sum_by_id.get(run.test_id)
        lrows = logs_by_id.get(run.test_id, [])
        req_val = int(srow["requests"]) if srow else -1
        ok = (srow is not None) and (req_val == len(lrows))
        a_ok = a_ok and ok
        a_parts.append(f"{run.mode}({run.test_id}): summary_requests={req_val}, log_rows={len(lrows)}")
    results.append(CheckResult("A", "Summary rows == test_log.csv rows", a_ok, "; ".join(a_parts)))

    # Check B1 (Integrity) & Check B2 (Observation: failures & rejected_503 by mode)
    b1_ok = True
    b1_parts: list[str] = []
    b2_all_zero = True
    b2_parts: list[str] = []
    for run in (milp_run, rr_run):
        sent_sum = sum(c.sent for c in run.clients.values())
        client_fail_sum = sum(c.failed for c in run.clients.values())
        srow = sum_by_id.get(run.test_id)
        lrows = logs_by_id.get(run.test_id, [])
        req_val = int(srow["requests"]) if srow else -1
        sum_failed = int(srow["failed"]) if srow else -1
        rej_503 = sum(1 for r in lrows if r.get("status") == "rejected_503")
        other_non_ok = sum(1 for r in lrows if r.get("status") not in ("ok", "rejected_503"))
        ok = (srow is not None) and (sent_sum > 0) and (sent_sum == req_val == len(lrows))
        b1_ok = b1_ok and ok
        per_c = {cid: cr.sent for cid, cr in run.clients.items()}
        b1_parts.append(f"{run.mode}: sent_sum={sent_sum} {per_c}, requests={req_val}, log_rows={len(lrows)}")

        mode_zero = (sum_failed == 0) and (client_fail_sum == 0) and (rej_503 == 0) and (other_non_ok == 0)
        b2_all_zero = b2_all_zero and mode_zero
        b2_parts.append(
            f"{run.mode}: summary_failed={sum_failed}, client_failed={client_fail_sum}, "
            f"rejected_503={rej_503}, other_non_ok={other_non_ok}, failed_eq_zero={mode_zero}"
        )
    results.append(CheckResult("B1", "Client sent sum == requests == log rows", b1_ok, "; ".join(b1_parts)))
    results.append(
        CheckResult(
            "B2",
            "Failures & rejected_503 counts by mode",
            b2_all_zero,
            "; ".join(b2_parts),
            observation=True,
        )
    )

    # Check C
    c_splits: dict[str, dict[str, tuple[int, int, int]]] = {}
    for run in (milp_run, rr_run):
        per_cid: dict[str, tuple[int, int, int]] = {}
        lrows = logs_by_id.get(run.test_id, [])
        for _no, cid, _tt, _r in CLIENT_SPECS:
            c_rows = [r for r in lrows if r.get("client_id") == cid]
            h = sum(1 for r in c_rows if r.get("task_type") == "heavy")
            lt = sum(1 for r in c_rows if r.get("task_type") == "light")
            per_cid[cid] = (len(c_rows), h, lt)
        c_splits[run.mode] = per_cid
    c_ok = (c_splits["milp"] == c_splits["round_robin"]) and all(v[0] > 0 for v in c_splits["milp"].values())
    results.append(
        CheckResult(
            "C",
            "Identical per-client workload across modes",
            c_ok,
            f"milp={c_splits['milp']}, round_robin={c_splits['round_robin']}",
        )
    )

    # Check D
    rr_rows = sorted(logs_by_id.get(rr_run.test_id, []), key=lambda r: int(r["dispatch_seq"]))
    expected_cycle = all(
        int(r["dispatch_seq"]) == idx + 1 and r["assigned_worker"] == f"worker-{(idx % 3) + 1}"
        for idx, r in enumerate(rr_rows)
    )
    rr_failover_vals = {r.get("failover") for r in rr_rows}
    rr_sched_vals = {r.get("scheduler_used") for r in rr_rows}
    d_ok = (
        len(rr_rows) > 0
        and expected_cycle
        and rr_failover_vals == {"false"}
        and rr_sched_vals == {"round_robin"}
        and rr_run.solver_call_count == 0
    )
    results.append(
        CheckResult(
            "D",
            "RR strict w1->w2->w3, zero failover, 0 solver calls",
            d_ok,
            f"rows={len(rr_rows)}, strict_cycle={expected_cycle}, failover={rr_failover_vals}, "
            f"scheduler_used={rr_sched_vals}, solver_call_count={rr_run.solver_call_count}",
        )
    )

    # Check E
    milp_rows = logs_by_id.get(milp_run.test_id, [])
    milp_sched_vals = {r.get("scheduler_used") for r in milp_rows}
    milp_mode_vals = {r.get("mode") for r in milp_rows}
    e_ok = len(milp_rows) > 0 and milp_run.solver_call_count > 0 and milp_sched_vals == {"ortools_milp"}
    results.append(
        CheckResult(
            "E",
            "MILP solver_call_count > 0 & scheduler_used=='ortools_milp'",
            e_ok,
            f"rows={len(milp_rows)}, solver_call_count={milp_run.solver_call_count}, "
            f"mode={milp_mode_vals}, scheduler_used={milp_sched_vals}",
        )
    )

    # Check F
    f_ok = True
    f_parts: list[str] = []
    for run in (milp_run, rr_run):
        lrows = logs_by_id.get(run.test_id, [])
        w_busy = [
            sum(float(r["exec_ms"]) for r in lrows if r.get("assigned_worker") == w and r.get("status") == "ok")
            for w in ("worker-1", "worker-2", "worker-3")
        ]
        recomputed = round(statistics.pstdev(w_busy), 2) if lrows else -1.0
        csv_val = float(sum_by_id[run.test_id]["busy_time_stddev"]) if run.test_id in sum_by_id else -2.0
        ok = abs(recomputed - csv_val) <= 0.01
        f_ok = f_ok and ok
        f_parts.append(f"{run.mode}: recomputed={recomputed}, csv={csv_val}, worker_busy={[round(x, 2) for x in w_busy]}")
    results.append(CheckResult("F", "Recomputed busy_time_stddev matches CSV", f_ok, "; ".join(f_parts)))

    # Check G
    g_ok = lock_probe == (409, 409)
    results.append(
        CheckResult(
            "G",
            "Mode lock & concurrent test lock (409)",
            g_ok,
            f"POST /api/v1/control/scheduler during running={lock_probe[0] if lock_probe else None}, "
            f"second POST /admin/test/start={lock_probe[1] if lock_probe else None}",
        )
    )

    # Check H
    protected = (
        "/api/v1/telemetry/workers",
        "/api/v1/control/snapshot",
        "/admin/stats/summary",
        "/api/v1/telemetry/redis",
        "/api/v1/benchmark/runs",
    )
    public = ("/healthz", "/test/status", "/", "/client")
    h_ok = all(auth_results[p] == 401 for p in protected) and all(auth_results[p] == 200 for p in public)
    results.append(CheckResult("H", "Auth 401 gates & public 200 routes", h_ok, json.dumps(auth_results)))

    # Check I
    new_rows = log_dict_rows[pre_log_count:]
    none_rows = [r for r in new_rows if r.get("test_id") == "none" and r.get("client_id") == "web"]
    web_logged_ids = [r.get("task_id", "") for r in none_rows]
    i_ok = web_statuses == [200, 200] and len(none_rows) == 2 and {r["task_type"] for r in none_rows} == {"light", "heavy"}
    results.append(
        CheckResult(
            "I",
            "Public POST /tasks web outside test -> test_id=none",
            i_ok,
            f"statuses={web_statuses}, workers={web_workers}, logged_task_ids={web_logged_ids}, matched_rows={len(none_rows)}",
        )
    )

    # Check J
    with httpx.Client(base_url=base_url, timeout=10.0) as sclient:
        results.append(_check_j_static_and_served(sclient))

    # Check K
    results.append(_check_k_secrets())

    # Check L
    l_cols_ok = (len(log_header) == 22 and log_header == TEST_LOG_COLUMNS) and (
        len(sum_header) == 19 and sum_header == TEST_SUMMARY_COLUMNS
    )
    clients_seen_vals = {
        sum_by_id[run.test_id].get("clients_seen") for run in (milp_run, rr_run) if run.test_id in sum_by_id
    }
    script_rows = [
        r
        for r in log_dict_rows
        if r.get("test_id") in (milp_run.test_id, rr_run.test_id) and str(r.get("client_id", "")).startswith("client-")
    ]
    script_fields_ok = len(script_rows) > 0 and all(
        r.get("client_rate") == "3.0" and r.get("client_task_type") in ("light", "heavy") for r in script_rows
    )
    web_blank_ok = len(none_rows) == 2 and all(
        r.get("client_rate") == "" and r.get("client_task_type") == "" for r in none_rows
    )
    capital_none_hits = [
        (idx, k, v)
        for idx, row in enumerate(log_dict_rows + sum_dict_rows)
        for k, v in row.items()
        if str(v).strip() == "None"
    ]
    l_ok = l_cols_ok and clients_seen_vals == {"3"} and script_fields_ok and web_blank_ok and len(capital_none_hits) == 0
    results.append(
        CheckResult(
            "L",
            "CSV 22/19 headers, client_rate/type, blank web, no 'None'",
            l_ok,
            f"log_cols={len(log_header)}, summary_cols={len(sum_header)}, clients_seen={clients_seen_vals}, "
            f"script_rows_filled={len(script_rows)}({script_fields_ok}), web_rows_blank={len(none_rows)}({web_blank_ok}), "
            f"literal_None_cells={len(capital_none_hits)}",
        )
    )

    return results


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    cfg = ClientSettings()
    parser = argparse.ArgumentParser(description="CloudBalance Final Acceptance Verification (A-L)")
    parser.add_argument("--controller", default=cfg.controller_url, help="Controller URL (default CB_BASE_URL)")
    parser.add_argument("--only-j", action="store_true", help="Run only Check J against the running controller")
    args = parser.parse_args(argv)

    base_url = args.controller.rstrip("/")
    if args.only_j:
        with httpx.Client(base_url=base_url, timeout=10.0) as sclient:
            j_res = _check_j_static_and_served(sclient)
        print(f"J | {'PASS' if j_res.passed else 'FAIL'} | {j_res.name} | {j_res.evidence}")
        return 0 if j_res.passed else 1

    admin_token = cfg.admin_token
    if not admin_token:
        print("[!] ADMIN_TOKEN missing from env / .env", file=sys.stderr)
        return 1

    print(f"Running CloudBalance Final Acceptance (A-L) [script-driven, not browser] against {base_url}")
    results = asyncio.run(_run_acceptance(base_url=base_url, admin_token=admin_token))

    print("\n=== FINAL ACCEPTANCE TABLE (A-L) [script-driven, not browser] ===")
    print("Check | Result | Name | Evidence")
    print("-" * 110)
    all_pass = True
    for r in results:
        status_str = "OBSERVATION" if r.observation else ("PASS" if r.passed else "FAIL")
        if not r.observation and not r.passed:
            all_pass = False
        print(f"{r.key} | {status_str} | {r.name} | {r.evidence}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
