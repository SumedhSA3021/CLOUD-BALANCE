# 02 — Task Creation & Dispatch Pipeline Trace

**Goal:** Confirm every task-creation/dispatch path routes through the single pipeline `execute_task_contract -> record_dispatch -> test_log.csv`, and report any bypass, direct worker call, or out-of-pipeline scheduler invocation.  
**Verdict:** **FAIL** — Core HTTP/simulator/load paths converge on `execute_task_contract`, **but** (1) `backend/app/api/benchmark.py` and `benchmark/run_benchmark.py` run scheduling outside the pipeline (with `benchmark.py` mutating global `SOLVER_CALL_COUNT` and `benchmark/run_benchmark.py` broken at import), (2) `scripts/verify_worker_b1.py` hits worker `:8001/execute` directly, and (3) `HTTPException` exits inside `execute_task_contract` skip `complete_inflight_task` and leak into timeout rows in `test_log.csv`.

---

## 1. Path-by-Path Trace

| Entry Path | Source (`file:line`) | Calls `execute_task_contract`? | Calls `record_dispatch`? | Logs to `data/test_log.csv`? | Direct Worker Call / Scheduler Outside Pipeline? | Verdict |
|---|---|---|---|---|---|---|
| `POST /tasks` | `backend/app/api/tasks.py:646-656` | **Yes** (`tasks.py:656`) | **Yes** (`tasks.py:268,295,528`) | **Yes** (`tasks.py:584` or drain `admin.py:334`) | No (HTTP to resolved worker `/execute`, or in-proc if `ip=="virtual"`) | **PASS** *(caveat on 4xx leak below)* |
| `POST /api/v1/tasks` | `backend/app/api/tasks.py:659-666` | **Yes** (`tasks.py:666`) | **Yes** | **Yes** | No | **PASS** |
| `POST /api/v1/control/traffic` (spike) | `backend/app/api/control.py:82-93` | **Yes** (`control.py:86`) | **Yes** | **Yes** (`test_id="none"` if idle, active `test_id` if running) | No; however `paused` / `lambda_rate` (`control.py:76-79`) are **ignored** by `tasks.py` | **PASS** *(control flags dead)* |
| `InternalLoadSimulator` | `backend/app/core/simulator.py:215-256` | **Yes** (`simulator.py:235`) via `AppProxyRequest` | **Yes** | **Yes** | No | **PASS** *(see `sim-` edge case below)* |
| `PoissonTrafficGenerator` / `cb-traffic` | `traffic/poisson_generator.py:198-226`, `traffic/cli.py:108` | **Yes** (`POST /tasks` at `poisson_generator.py:200`) | **Yes** | **Yes** | No | **PASS** |
| `tools/load_client.py` | `tools/load_client.py:74-96` | **Yes** (`POST /tasks` at `load_client.py:90`) | **Yes** | **Yes** | No | **PASS** |
| `PublicTasksPage.tsx` (`/`) | `frontend/src/pages/PublicTasksPage.tsx:93,124`, `api.ts:142` | **Yes** (`POST /tasks` at `api.ts:142`) | **Yes** | **Yes** | No | **PASS** |
| Verification scripts (`verify_rr_isolation.py`, `verify_milp_inflight.py`, `smoke_test.py`) | `scripts/verify_rr_isolation.py:71`, `verify_milp_inflight.py:60`, `smoke_test.py:137,147` | **Yes** (`POST /tasks`) | **Yes** | **Yes** | No | **PASS** |
| `scripts/verify_worker_b1.py` | `scripts/verify_worker_b1.py:15,49,75,96,113` | **No** | **No** | **No** | **Direct worker call** to `http://127.0.0.1:8001/execute` | **BYPASS** (dev worker test script) |
| `GET /api/v1/benchmark/runs` & `POST /api/v1/benchmark/run` | `backend/app/api/benchmark.py:32-207, 219, 242` | **No** | **No** | **No** | **Yes — Instantiates `ORToolsMILPScheduler` & `RoundRobinScheduler` directly (`benchmark.py:69-70,115`) and mutates global `SOLVER_CALL_COUNT`!** | **FAIL** |
| `benchmark/run_benchmark.py` (`make bench`, CI) | `benchmark/run_benchmark.py:45-48, 132-183` | **No** | **No** | **No** | **Imports deleted `app.schedulers.least_connections.LeastConnectionsScheduler` (`run_benchmark.py:46`) -> `ModuleNotFoundError`!** | **FAIL (BROKEN)** |

---

## 2. Detailed Pipeline & Bug Evidence

### 2.1 Canonical Single Pipeline (`execute_task_contract`, `backend/app/api/tasks.py:188-643`)
1. Payload size check via route dependency `_enforce_max_payload_size` (`tasks.py:163-185`) AND post-model check (`tasks.py:205-211`).
2. Draining gate returns HTTP `409` (`tasks.py:215-219`).
3. Per-`client_id` sliding-window rate limit check (`tasks.py:221-223`).
4. Mode resolved ONCE at arrival into `task.mode` (`tasks.py:240, 249`).
5. Branching:
   - `task.mode == "round_robin"` -> `redis_client.incr("rr_counter")` -> `worker_ids[(n - 1) % len(worker_ids)]` -> `in_flight.increment` -> `live_dispatch_tracker.record_dispatch` (`tasks.py:262-268`).
   - `task.mode != "round_robin"` (`milp`) -> `async with milp_lock:` -> `milp_sched.assign` -> `in_flight.increment` -> `live_dispatch_tracker.record_dispatch` (`tasks.py:270-299`).
6. HTTP dispatch to worker `/execute` (or `_execute_local_workload` only when `worker_ip == "virtual"`, `tasks.py:444-490`), with `ConnectError`/`NetworkError` failover (`tasks.py:493-556`).
7. Logging at `tasks.py:582-605`: `log_task_record(...)` writes one row to `data/test_log.csv` (unless `complete_inflight_task` returns `False` because drain timeout already wrote `status="timeout"` at `admin.py:334-355`).

### 2.2 Concrete Bugs & Bypasses Found

1. **Out-of-pipeline scheduling in `benchmark.py` pollutes live `SOLVER_CALL_COUNT` (`backend/app/api/benchmark.py:69,115` & `backend/app/schedulers/ortools_milp.py:295-296`):**
   - `run_seeded_benchmark_simulation` constructs `ORToolsMILPScheduler` and calls `.assign(...)` on synthetic hardcoded data (`ip_address="10.128.0.10"`).
   - Inside `ORToolsMILPScheduler.assign()` (`ortools_milp.py:185, 295-296`), it unconditionally reads global `live_dispatch_tracker.get_worker_cumulative(...)` and increments module-global `SOLVER_CALL_COUNT += 1`.
   - Triggering `/api/v1/benchmark/run` (or opening `/benchmark` when empty) during or between live tests inflates `GET /api/v1/control/solver-metrics` even if the live cluster is in `round_robin` mode (missing `is_test_running()` guard).
2. **`benchmark/run_benchmark.py` crashes with `ModuleNotFoundError` (`benchmark/run_benchmark.py:46,134`):**
   - Imports `from app.schedulers.least_connections import LeastConnectionsScheduler`, which was deleted from `backend/app/schedulers/`. Both `Makefile:20` and `.github/workflows/ci.yml:45` invoke `python benchmark/run_benchmark.py`.
3. **4xx `HTTPException` exits in `execute_task_contract` skip CSV completion cleanup (`tasks.py:348-369, 434-436, 464-470, 491-492, 582-611`):**
   - `test_manager.register_inflight_task(task_id, ...)` (`tasks.py:349`) and `client_stats.record_enqueue(...)` (`tasks.py:330`) run BEFORE dispatching HTTP / local workload.
   - If a worker returns HTTP `400`/`413`/`422` (`tasks.py:470`) or `_execute_local_workload` raises `HTTPException(400)` (`worker/executor.py:113`), `HTTPException` is re-raised (`tasks.py:491-492`), bypassing `test_manager.complete_inflight_task(task_id)` (`tasks.py:582`) and `client_stats.record_assigned(...)` (`tasks.py:611`).
   - Result: during an active test, a bad-input `400` request remains stuck in `test_manager._active_tasks`, forces `DRAINING` to wait the full `drain_timeout_sec` (15s), and gets logged as `status="timeout"` at `admin.py:334-356`. `client_stats.queued_count` also leaks `+1`.
4. **`sim-` client ID prefix skips test counter attribution (`tasks.py:607-608`):**
   - `if test_id != "none" and not str(req.client_id).startswith("sim-"): test_manager.record_task_result(worker_status)`.
   - Any external caller submitting `"client_id": "sim-anything"` via `POST /tasks` during a running test is logged to `test_log.csv` and `test_summary.csv`, yet omitted from `/test/status` counters (`sent`/`ok`/`failed`).
5. **Control pause flag ignored (`control.py:78-79`):**
   - `POST /api/v1/control/traffic` sets `scheduler_state.set_paused(...)`, which is broadcast on WS (`broadcaster.py:78`), **never checked** in `execute_task_contract`.
6. **Spike route bypasses HTTP header byte guard (`control.py:86`):**
   - `control.py` calls `execute_task_contract` directly, skipping router dependency `_enforce_max_payload_size` (mitigated because `execute_task_contract` re-checks `req.model_dump_json()` size at `tasks.py:207`).
