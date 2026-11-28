# CloudBalance Final Static Audit Report (PART 1)

**Audit Type:** Read-only static inspection (zero runtime tests executed; zero code, tests, config, `frontend/dist`, or `Local-Version/` modified).  
**Output Directory:** [`audit/`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/)

---

## Executive Verdict Summary (PART 1: Items 1–7)

| # | Audit Area | Verdict | Core Summary | Detailed Report |
|---|---|---|---|---|
| 1 | **Route Inventory & Callers** | **WARN / FAIL** | Dead aliases (`GET /api/v1/health`, `WS /api/v1/ws`), test-only `/api/v1/control/*` + `/api/v1/mongo`, asymmetric `POST /tasks` vs `/api/v1/tasks` auth, broken `useWebSocket()` in `DashboardPage.tsx`, and incomplete `nginx.conf` | [`01_route_inventory.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/01_route_inventory.md) |
| 2 | **Pipeline Duplication & Bypasses** | **FAIL** | Runtime task paths share `execute_task_contract -> record_dispatch -> test_log.csv`, **but** `benchmark.py` schedules out-of-pipeline & pollutes `SOLVER_CALL_COUNT`, `benchmark/run_benchmark.py` crashes on import, and 4xx `HTTPException`s leak `test_manager._active_tasks` | [`02_pipeline_trace.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/02_pipeline_trace.md) |
| 3 | **Scheduler Mode & Isolation** | **WARN / FAIL** | Dispatch reads mode once into `task.mode` with strict RR/MILP separation in `tasks.py`, **but** `start_test`/`end_test` leaves Redis `sched_mode` & `SchedulerStateService` out of sync (split-brain UI vs routing), `scheduler_used="ortools_milp"` vs `mode="milp"`, and MILP `cumul_penalty` impairs single-host balance | [`03_scheduler_analysis.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/03_scheduler_analysis.md) |
| 4 | **Counters & Locks** | **WARN / FAIL** | `InFlightTracker` (`max(0, ...)` under `threading.Lock`) & `rr_counter` (`INCR`) are sound, **but** `workers_cache` is read before `milp_dispatch_lock` (`tasks.py:270,499`), `in_flight.increment` precedes `try:` (`267,294` vs `325`), 4xx errors leak `_active_tasks`/`queued_count`, and real Redis `DECR` lacks clamp | [`04_counters_locks.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/04_counters_locks.md) |
| 5 | **Hardcoded Values & Config** | **WARN / FAIL** | Frontend uses relative URLs (`""` / `window.location`) for tunnel readiness, **but** `("worker-1","worker-2","worker-3")` is hardcoded in `admin.py`/`test_hooks.py`/`live_stats.py`/`OpsCenterPage.tsx`, `tasks.py:452` ignores `dispatch_timeout_sec`, `backend/.env` shadows root `.env`, and `docker-compose.yml` + `infra/gcp/*` lack `ADMIN_TOKEN`/`WORKER_SECRET` | [`05_hardcoded_values.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/05_hardcoded_values.md) |
| 6 | **Auth Matrix & Secrets** | **FAIL / WARN** | `ADMIN_TOKEN`/`WORKER_SECRET` enforced on admin/telemetry/WS with no `Settings` defaults and `.env` is gitignored, **but** `POST /tasks` vs `/api/v1/tasks` disagree on `verify_api_key`, `Settings.api_key` defaults to `"cb-dev-api-key-2026"`, `/ready` leaks cluster metadata, `?token=` is sent in WS URL, and `Local-Version/` still tracks `"cb-admin-secret-2026"` in git | [`06_auth_matrix.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/06_auth_matrix.md) |
| 7 | **SSE, IP Logging, CORS & Rate Limiter** | **PASS / WARN** | Zero SSE (`0` matches), zero app/CSV/DB client IP logging, rate limiter keyed on `client_id` with `>=1200/min` test floor; **warnings** for CORS default `["*"]`, uvicorn stdout access logs, dead `rate_limit_per_sec`, unbounded >1024 bucket growth, and unthrottled `/admin/auth/login` | [`07_sse_ip_cors_ratelimit.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/07_sse_ip_cors_ratelimit.md) |

---

## Ranked Concrete Bugs & Gaps Discovered (All Evidence-Backed)

### Critical / High
1. **Broken WebSocket on `/benchmark` (`frontend/src/pages/DashboardPage.tsx:8`):** `useWebSocket()` is invoked with no `token`, so `useWebSocket.ts:107-112` keeps `/benchmark` permanently `DISCONNECTED` and never fetches live snapshots.
2. **Broken Docker/Nginx reverse-proxy routing (`infra/nginx/nginx.conf:14-47`):** `/tasks`, `/admin/*`, `/test/status`, `/healthz` are not proxied to `controller:8000` and fall through to React `index.html`.
3. **Broken `docker-compose.yml` & `infra/gcp/startup-*.sh`:** Omit required `ADMIN_TOKEN`, `WORKER_SECRET`, and `WORKER_URLS`; controller fails startup (`config.py:89-96`) and GCP workers fail telemetry auth (`401`).
4. **Broken `benchmark/run_benchmark.py` (`benchmark/run_benchmark.py:46,134`):** Imports deleted `app.schedulers.least_connections.LeastConnectionsScheduler`, causing immediate `ModuleNotFoundError` (also breaks `make bench` and `.github/workflows/ci.yml:45`).
5. **Global `SOLVER_CALL_COUNT` pollution & unsynchronized mutation from `benchmark.py` (`backend/app/api/benchmark.py:69,115,219,242`, `ortools_milp.py:295-296`):** Calling `/api/v1/benchmark/run` (or `/runs` when empty) invokes `ORToolsMILPScheduler.assign()` inside `asyncio.to_thread` with no `is_test_running()` lock, incrementing `SOLVER_CALL_COUNT` even during `round_robin` tests.
6. **Scheduler Mode Split-Brain (`admin.py:219,383-395`, `test_hooks.py:55,103,116-122`, `broadcaster.py:73`):** `start_test` writes Redis `sched_mode` without updating `scheduler_state`, and `end_test()` leaves the last test's `sched_mode` in Redis. After a `round_robin` test returns to `idle`, public `POST /tasks` silently stays on `round_robin` while `/ready` and the `/ops` Header report `OR-Tools MILP`.
7. **In-test `HTTPException` (`400/413/422`) leaks `test_manager._active_tasks` & `client_stats.queued_count` (`tasks.py:330,349,470,492,582,611`):** Causes 15-second `DRAINING` stall and writes false `status="timeout"` rows into `data/test_log.csv`.
8. **Git-tracked secrets & untracked active code (`.gitignore:48-57`, `Local-Version/backend/app/api/admin.py:46`):** Git HEAD still tracks `"cb-admin-secret-2026"` & `"cb-dev-api-key-2026"` inside `Local-Version/`, while root `backend/`, `frontend/`, `worker/`, `traffic/`, `infra/` are ignored by `.gitignore:48-55`.

### Medium
9. **Stale `workers_cache` outside `milp_dispatch_lock` (`tasks.py:270,288,499`):** `get_active_workers()` runs before acquiring `milp_lock`, and MILP failover (`workers_cache or ...`) reuses pre-lock telemetry instead of querying non-evicted workers.
10. **Asymmetric `verify_api_key` (`tasks.py:646-666`) + hardcoded `Settings.api_key` default (`config.py:112`):** `POST /api/v1/tasks` enforces `verify_api_key`, while `POST /tasks` bypasses it; default key is `"cb-dev-api-key-2026"`.
11. **`scheduler_used="ortools_milp"` vs `mode="milp"` mismatch (`tasks.py:299` vs `tasks.py:110`):** Causes automated exact-match assertions on `scheduler_used == "milp"` to fail.
12. **MILP single-host imbalance (`ortools_milp.py:185-210`):** `cumul_penalty` forces equal task counts regardless of cost, steering heavy jobs onto the lowest-baseline worker (`worker-3`) and increasing `busy_time_stddev` and queue delay vs RR.
13. **Hardcoded `worker-1..3` lists (`admin.py:323`, `test_hooks.py:23`, `live_stats.py:10`, `OpsCenterPage.tsx:56`):** Breaks custom `WORKER_URLS` IDs or `>3` workers.
14. **Admin WS token sent in URL query string (`useWebSocket.ts:27`) & raw `sessionStorage` (`AdminAuthContext.tsx:70`), plus unthrottled `/admin/auth/login` (`admin.py:457`).**
15. **Silent `backend/.env` override (`config.py:75`, `backend/.env`) & ignored `Settings` fields (`dispatch_timeout_sec` ignored at `tasks.py:452`, `rate_limit_per_sec` dead at `config.py:152`).**

### Low / Informational
16. **Dead / overlapping routes (`GET /api/v1/health`, `WS /api/v1/ws`, `GET /api/v1/mongo` duplicating `/telemetry/mongo`, `POST /api/v1/control/traffic`, `kill`, `revive`).**
17. **Unauthenticated `GET /ready` cluster metadata disclosure (`health.py:38-45`) and port number in offline error (`tasks.py:555`).**
18. **`in_flight.increment` occurs outside `try:` (`tasks.py:267,294` before `325`); real Redis `DualRedisClient.decr` lacks zero-clamp (`redis_client.py:273`).**
19. **`sim-` client_id prefix skips `test_manager.record_task_result` (`tasks.py:607`); `scheduler_state.paused` never checked (`control.py:79`); `ClientRateLimiter._hits` lacks cap when >1024 active keys arrive within 60s (`security.py:46-49`).**
20. **`scripts/verify_worker_b1.py:15` & `traffic/cli.py:24`:** Lack env-var base URL overrides; `uvicorn` controller lacks `--no-access-log` (`run_cluster.py:160-169`).
