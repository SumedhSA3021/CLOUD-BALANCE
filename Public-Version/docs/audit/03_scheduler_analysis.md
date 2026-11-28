# 03 — Scheduler Mode & Isolation Audit

**Goal:** List every read/write of scheduler mode, verify mode is frozen once at arrival into `task.mode`, confirm Round Robin never reaches the OR-Tools MILP solver, and confirm MILP never uses Redis `rr_counter`.  
**Verdict:** **WARN / FAIL** — Dispatch path isolation inside `execute_task_contract` **PASSES** (mode read once at arrival; strict RR/MILP separation), **but** there is a **split-brain bug between Redis `sched_mode` and `SchedulerStateService`**, plus a `scheduler_used` naming mismatch (`"ortools_milp"` vs `"milp"`), global `SOLVER_CALL_COUNT` pollution from `/api/v1/benchmark/*`, and flawed MILP objective behavior.

---

## 1. Complete Inventory of Mode Reads & Writes

### Writes
| Location (`file:line`) | Target Written | Trigger | Notes |
|---|---|---|---|
| `backend/app/services/scheduler_state.py:28-32` | `SchedulerStateService._active_scheduler_name` | App startup (`create_app` -> `cfg.default_scheduler`) | Does **not** initialize Redis `sched_mode` |
| `backend/app/services/scheduler_state.py:54-59` | `SchedulerStateService._active_scheduler_name` | `POST /api/v1/control/scheduler` | — |
| `backend/app/api/control.py:42-44` | `scheduler_state` + Redis `"sched_mode"` (`"round_robin"` or `"milp"`) | `POST /api/v1/control/scheduler` | Rejected with 409 if `is_test_running()` (`control.py:34`) |
| `backend/app/schedulers/test_hooks.py:82-85` | Module globals `_TEST_RUNNING`, `_TEST_MODE`, `_TEST_METADATA` | `POST /admin/test/start` -> `start_test()` | Stores `metadata["mode"]` |
| `backend/app/schedulers/test_hooks.py:55,103,111` & `admin.py:234` | Redis `"sched_mode"` (`"round_robin"` or `"milp"`) | `start_test()` / `reset_redis_test_keys()` | **Never updates `scheduler_state`!** |
| `backend/app/schedulers/test_hooks.py:116-122` | Module globals `_TEST_RUNNING=False`, `_TEST_MODE=None`, `_TEST_METADATA={}` | `end_test()` via `admin.py:395` | **Leaves Redis `"sched_mode"` overwritten with last test's mode!** |
| `backend/app/api/admin.py:242` / `387` | `test_manager.mode` | `start()` / `_reset_to_idle()` | Drives `/test/status` and `test_summary.csv` `mode` column |

### Reads
| Location (`file:line`) | Source Read | Purpose | Notes |
|---|---|---|---|
| `backend/app/api/tasks.py:95-110, 240, 249` | 1. `test_hooks.get_current_test_metadata()["mode"]`<br>2. Redis `"sched_mode"`<br>3. `scheduler_state.active_scheduler_name` | Resolves `arrival_mode` and freezes it onto **`task.mode`** (`tasks.py:249`) | Read **once** per task at arrival |
| `backend/app/api/tasks.py:262, 305, 354, 507, 586` | `task.mode` | Decision (`round_robin` vs `milp`), logging, `register_inflight_task`, failover strategy, `test_log.csv` `mode` column | Never re-reads any global or Redis mode after line 249 |
| `backend/app/api/health.py:43` | `scheduler_state.active_scheduler_name` | `/ready` `"active_scheduler"` | **Stale** during/after `/admin/test/start` |
| `backend/app/services/broadcaster.py:73` | `scheduler_state.active_scheduler_name` | WebSocket `CLUSTER_SNAPSHOT.active_scheduler` | **Stale** during/after `/admin/test/start` |
| `backend/app/api/admin.py:182, 376` | `test_manager.mode` | `/test/status` & `write_test_summary` | Returns `"none"` when idle |
| `backend/app/models/schemas.py:117, 125-126` | `Task.from_request(..., mode)` | Used by `benchmark.py:62` and unit tests (`test_models_and_core.py:73`) | Unused by `tasks.py` |

---

## 2. Single-Read & Isolation Verification

1. **Mode frozen once at arrival into `task.mode`:** **PASS.**
   - `_resolve_arrival_mode` executes at `tasks.py:240` and sets `Task(..., mode=arrival_mode)` at `tasks.py:249`.
   - Dispatch (`tasks.py:262`) and failover (`tasks.py:507`) branch exclusively on `task.mode`. Nothing after line 249 reads Redis `sched_mode`, `_TEST_MODE`, or `scheduler_state.active_scheduler_name`.
   - Minor note: `tasks.py:234-239` computes `test_meta = {}` when `TestState.ARMED`, while `_resolve_arrival_mode` (`tasks.py:101-102`) re-reads `get_current_test_metadata()` directly (returns active test's mode during `ARMED`, which also matches Redis `sched_mode` set by `start_test()`).

2. **RR never reaches MILP solver:** **PASS (runtime dispatch), FAIL (via unguarded benchmark endpoint).**
   - In `tasks.py:262-268`: `if task.mode == "round_robin":` uses `await redis_client.incr("rr_counter")` and indexes `worker_ids[(n - 1) % len(worker_ids)]`. It never calls `_get_milp_scheduler` or `ORToolsMILPScheduler.assign()`.
   - In failover (`tasks.py:507-514`): `if task.mode == "round_robin":` picks next live worker cyclically in `worker_ids` without touching OR-Tools.
   - **Isolation breach outside dispatch:** `POST /api/v1/benchmark/run` (`benchmark.py:234`) and `GET /api/v1/benchmark/runs` when empty (`benchmark.py:218-221`) have no `is_test_running()` check and invoke `ORToolsMILPScheduler.assign()`, incrementing global `SOLVER_CALL_COUNT` (`ortools_milp.py:296`) even while a `round_robin` live test is running.

3. **MILP never uses Redis `rr_counter`:** **PASS.**
   - `tasks.py:270-299` never reads or increments Redis `rr_counter`.
   - `ORToolsMILPScheduler` (`backend/app/schedulers/ortools_milp.py:65, 178, 209`) uses an internal instance counter `self._rr_tie_break` solely as a `0.01`-weighted tie-breaker among equal-cost workers, completely separate from Redis `rr_counter`.

---

## 3. Concrete Bugs & Discrepancies Found

1. **BUG — Split-brain between Redis `sched_mode` and `SchedulerStateService` (`admin.py:219,383-395`, `test_hooks.py:55,103,116-122`, `broadcaster.py:73`):**
   - `ActiveTestManager.start()` (`admin.py:219-234`) writes the test's `mode` into Redis `sched_mode` via `start_test()`, **without** updating `scheduler_state.set_scheduler(...)`. Consequently, during a `round_robin` test started via `/ops`, `GET /ready` (`health.py:43`), WebSocket snapshots (`broadcaster.py:73`), and the `/ops` Header (`Header.tsx:52`) continue displaying `OR-Tools MILP`.
   - Worse, when the test ends, `end_test()` (`test_hooks.py:116-122`) clears `_TEST_METADATA` but **never clears or restores Redis `sched_mode`**. Subsequent idle `POST /tasks` arrivals read Redis `sched_mode` (`tasks.py:105`) and silently run in the last test's mode (`round_robin`), while `/ops` Header and `/ready` claim `OR-Tools MILP` (`DEFAULT_SCHEDULER`).
2. **BUG — `scheduler_used="ortools_milp"` vs `mode="milp"` naming mismatch (`tasks.py:110, 299`):**
   - Requests and tests normalize mode to `"milp"` (`tasks.py:110`, `admin.py:77`), yet `tasks.py:299` logs `scheduler_used="ortools_milp"` into `data/test_log.csv` and `TaskContractResponse`. Any strict check expecting `scheduler_used == "milp"` fails (as recorded in `proof/PROOF_REPORT.md` Check E).
3. **BUG — MILP objective causes worse balance than RR on staggered single-host CPU baselines (`ortools_milp.py:185-210`):**
   - `cumul_penalty = min(20.0, float(rel_cumul) * 5.0)` forces equal task *counts* across workers while `Minimize(z_var + 0.001 * m_var + tie_break_expr)` steers heavy (`35%` CPU) tasks to the lowest baseline-CPU worker (`worker-3` at `9%`, vs `worker-2` at `18%`), increasing queue delay and `busy_time_stddev` vs RR on single-host runs (`proof/PROOF_REPORT.md` Section 4).
