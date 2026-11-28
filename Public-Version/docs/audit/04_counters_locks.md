# 04 — Counters, Locks & Exit-Path Safety Audit

**Goal:** Inspect `rr_counter` atomicity, in-flight counter increment/decrement under `try/finally` across every exit path, `milp_dispatch_lock` scope, and risks of leaks, stale snapshots, or double-decrements.  
**Verdict:** **WARN / FAIL** — `InFlightTracker` (`max(0, val - 1)`) prevents negative in-memory counts and handles `503`/`504`/`ConnectError`/`HTTPException` inside `try/finally`, **but** there are concrete bugs around (1) `in_flight.increment` placed **before** `try:` (`tasks.py:267,294` vs `325`), (2) `workers_cache` fetched **outside** `milp_dispatch_lock` (`tasks.py:270` vs `288`) and reused during MILP failover (`tasks.py:499`), (3) unguarded `HTTPException` exits leaking `test_manager._active_tasks` + `client_stats.queued_count`, (4) real Redis `DECR` lacking zero-clamping (`redis_client.py:273`), and (5) hardcoded `("worker-1", "worker-2", "worker-3")` loops in drain/stats.

---

## 1. Counter & Lock Inventory

| Mechanism | Definition / Guard | Atomic? | Notes (`file:line`) |
|---|---|---|---|
| `rr_counter` (Local) | `InMemoryTTLStore.incr` (`backend/app/core/redis_client.py:97-110`) guarded by `asyncio.Lock` | **Yes** (single coroutine atomic read-mod-write) | `tasks.py:263` |
| `rr_counter` (Redis) | `DualRedisClient.incr` (`redis_client.py:258-268`) -> Redis `INCR` | **Yes** | Falls back to un-synced `_memory_store` on error (`redis_client.py:266`) |
| `milp_dispatch_lock` | `asyncio.Lock` on `app.state.milp_dispatch_lock` (`main.py:59,111`, `tasks.py:154-160`) | **Yes** across coroutines on event loop | Scoped around `milp_sched.assign` + `in_flight.increment` + `live_dispatch_tracker.record_dispatch` (`tasks.py:288-297`) |
| `InFlightTracker._worker_counts` | `threading.Lock` (`backend/app/schedulers/base.py:40-62`) | **Yes** (`increment`, `decrement`, `get_count`) | `decrement` clamps via `max(0, ...)` (`base.py:55`), preventing negative values |
| `InFlightTracker._reservations` | `threading.Lock` (`base.py:73-134`) | **Yes** | **Unused in `tasks.py`**, because `tasks.py:289` passes `record_in_flight=False`; `cluster_state.py:54` calls `release_worker` on empty dict |
| Redis `inflight:{w}` & `cluster:inflight:{w}` | `DualRedisClient.incr` / `.decr` (`tasks.py:326-327, 522-527, 565-566`) | `INCR`/`DECR` individual ops atomic | **No scheduler reads these keys**; real Redis `decr` does **not** clamp at `0` (`redis_client.py:273`) |
| `LiveDispatchTracker` | `threading.Lock` (`backend/app/core/live_stats.py:18,35,41,46,51`) | **Yes** | Ignores any `worker_id` not in hardcoded `("worker-1","worker-2","worker-3")` (`live_stats.py:32`) |
| `SOLVER_CALL_COUNT` | Module global `int` (`backend/app/schedulers/ortools_milp.py:17,25-28,295-296`) | Safe in single-thread event loop (`assign` is sync); **NOT thread-safe** (`benchmark.py` runs in `asyncio.to_thread`!) | **Race / cross-contamination:** `benchmark.py:219,242` runs `ORToolsMILPScheduler.assign` in worker threads (`+= 1` unprotected)! |
| Worker `queue_lock` & `semaphore` | `asyncio.Lock` + `asyncio.Semaphore` (`worker/executor.py:268-269, 405, 520-524`) | **Yes** | Properly released in worker `try/finally` (`executor.py:520-524`) |

---

## 2. `tasks.py` Increment / Decrement Exit-Path Matrix (`backend/app/api/tasks.py`)

In `execute_task_contract`:
- **Increment sites:**
  - `worker_inflight_at_dispatch = in_flight.increment(assigned_worker)` at `tasks.py:267` (RR) and `tasks.py:294` (MILP).
  - `await redis_client.incr(...)` at `tasks.py:326-327` (inside `try:`).
- **`finally:` site:** `tasks.py:563-566` (`in_flight.decrement(assigned_worker)`, `redis_client.decr(...)`).

| Exit Path | `tasks.py` Lines | `in_flight` Balanced? | Redis `inflight:*` Balanced? | `test_manager` & `client_stats` Clean? | Finding |
|---|---|---|---|---|---|
| Normal HTTP `200` | `454-463 -> 563-566` | **Yes** (`+1` -> `-1`) | **Yes** | **Yes** | Clean |
| Worker `503` (Queue full) | `471-472 -> 563-566` | **Yes** (`+1` -> `-1`) | **Yes** | **Yes** (`status="rejected_503"`, no failover) | Clean |
| Worker `504` / `408` / `TimeoutException` | `473-485, 557-559 -> 563-566` | **Yes** (`+1` -> `-1`) | **Yes** | **Yes** (`status="timeout"`, no failover) | Clean |
| Virtual in-process `ok` | `444-445 -> 563-566` | **Yes** (`+1` -> `-1`) | **Yes** | **Yes** | Clean |
| `HTTPException(400/413/422)` from worker (`_dispatch_http`) or virtual CGPA/hash validation | `434-436, 464-470, 491-492 -> 563-566` | **Yes** (`finally` runs) | **Yes** (`finally` runs) | **FAIL — Leaks!** Skips `complete_inflight_task` (`582`) and `record_assigned` (`611`) | Left in `_active_tasks` -> 15s drain stall + bogus `status="timeout"` CSV row! |
| `ConnectError`/`NetworkError` -> Failover `200`/`503`/`504`/`ConnectError` | `493-550 -> 563-566` | **Yes** (`decr W1` at `521`, `incr W2` at `525`, `decr W2` in `finally` `564`) | **Yes** (`522-527` -> `565-566`) | **Yes** (`update_inflight_worker` at `530`, `failover=True`) | **Gap:** Failover `HTTPException(400/413/422)` still exits to `finally` cleanly for `in_flight` (`W2`), still leaks `_active_tasks`. |
| `ConnectError`/`NetworkError` -> No `remaining` workers (or `allow_virtual=False`) | `551-556 -> 563-566` | **Yes** (`+1 W1` -> `-1 W1`) | **Yes** | **Yes** (`status="unavailable"`, `failover=False`) | Clean |
| Cancellation (`CancelledError`) BEFORE line `325` | `267/294 .. 324` | **Leak Risk** (incremented outside `try:`) | N/A | N/A | Only synchronous code between `267/294` and `325`, but structurally unsafe |
| Cancellation DURING `521-527` (failover swap) | `521-527 -> 563-566` | **Double-decr blocked** by `max(0, ...)` if after `521` before `524`; safe after `524` | **Negative risk on real Redis** (`DECR` without clamp if `522-527` interrupted mid-way) | Leaks `_active_tasks` | Non-atomic swap across 7 statements (`521-527`) with 4 `await`s |
| Drain deadline expires while HTTP call is hung (`admin.py:358-359`) | `admin.py:359` (`in_flight.clear()`) -> later `tasks.py:564` | **Clamped to `0`** (`base.py:55`), safe | **Real Redis goes `-1`!** (`admin.py` clears `in_flight` at `359` without resetting Redis `inflight:*`, or `start_test` zeroes it later and hung task `decr`s to `-1`) | Logged once as `timeout` (`complete_inflight_task` prevents duplicate CSV row at `582`) | Real Redis `decr` lacks clamp |

---

## 3. Lock Scope & Concurrency Findings

1. **`workers_cache` fetched OUTSIDE `milp_dispatch_lock` (`backend/app/api/tasks.py:270-297`):**
   - Line `270` (`workers_cache = await cluster_state.get_active_workers()`) executes before acquiring `milp_lock` at line `288`.
   - Under concurrent load when one worker crashes (`evict_worker` at `498`) or sends updated telemetry (`update_telemetry`), coroutines queued on `milp_lock` keep solving over a pre-lock `workers_cache` containing evicted workers.
   - Worse, during MILP failover (`tasks.py:499`: `live_workers = workers_cache or await cluster_state.get_active_workers()`), because `workers_cache` is non-empty, it does **not** re-read `cluster_state.get_active_workers()` and may attempt failover to a worker already evicted moments earlier by a peer task!
2. **Synchronous OR-Tools CBC solve inside `async with milp_lock:` (`tasks.py:288-289`, `ortools_milp.py:298`):**
   - Calling `solver.Solve()` synchronously blocks the asyncio event loop thread (typically 1–10ms, up to `solver_time_limit_ms=50`ms).
3. **`test_manager` & `client_stats` leak on 4xx `HTTPException` (`tasks.py:330, 349, 434-436, 470, 492, 582, 611`):**
   - `HTTPException` exits after line `349` leave the task registered in `test_manager._active_tasks`, delaying transition from `DRAINING -> IDLE` by 15 seconds and falsely writing a `status="timeout"` row in `data/test_log.csv`.
4. **Hardcoded worker IDs in `DRAINING` loop (`admin.py:322-324`):**
   - `for w in ("worker-1", "worker-2", "worker-3"): active += in_flight.get_count(w)` ignores custom `worker_id` names or >3 workers configured via `WORKER_URLS`.
5. **Non-atomic `SOLVER_CALL_COUNT += 1` across `asyncio.to_thread` (`benchmark.py:219,242` vs `ortools_milp.py:295-296`):**
   - `benchmark.py` runs `run_seeded_benchmark_simulation` inside `asyncio.to_thread`, mutating the same module global `SOLVER_CALL_COUNT` read/written by the event loop in `tasks.py`/`control.py`/`test_hooks.py` without a lock.
6. **`DualRedisClient` silent split fallback (`redis_client.py:181-277`):**
   - When `CB_LOCAL_MODE=false` and any transient Redis exception happens on `incr`/`decr`/`get`/`set`, `DualRedisClient` flips `self._using_memory = True` permanently without reconnecting or copying `rr_counter`/`sched_mode`/`cluster:worker:*`.
