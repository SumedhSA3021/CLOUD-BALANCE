# 01 — Backend Route Inventory & Callers Audit

**Scope:** All FastAPI routes registered in `backend/app/main.py` and `backend/app/api/*.py`, plus the separate worker FastAPI app in `worker/executor.py`.  
**Verdict:** **WARN / FAIL** — Multiple dead/overlapping routes exist (`GET /api/v1/health`, `GET /api/v1/mongo`, `WS /api/v1/ws`, test-only `/api/v1/control/*`), `/api/v1/tasks` vs `/tasks` have asymmetric `verify_api_key` guards, `DashboardPage` (`/benchmark`) fails to pass a token to `useWebSocket`, and `infra/nginx/nginx.conf` fails to proxy `/tasks`, `/admin/*`, `/test/*`, and `/healthz`.

---

## 1. Controller API & WebSocket Route Matrix

| # | Method | Path | Auth Enforced | Handler (`file:line`) | Frontend Callers | Script / Tool Callers | Pytest Test Callers | Status / Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | `GET` | `/health` | Public | `health_check` (`backend/app/api/health.py:17-22`) | — | `infra/nginx/nginx.conf:24` | `test_controller_api_and_services.py:31` | Overlaps with `/healthz` and `/api/v1/health` |
| 2 | `GET` | `/healthz` | Public | `health_check` (`backend/app/api/health.py:18-22`) | `vite.config.ts:25` (proxy) | `scripts/smoke_test.py:82` | `test_controller_api_and_services.py:34`, `test_edge_cases_senior_audit.py:919` | Primary health probe; missing from `infra/nginx/nginx.conf` |
| 3 | `GET` | `/api/v1/health` | Public | `health_check` (`backend/app/api/health.py:19-22`) | **None** | **None** | **None** | **DEAD / uncalled alias** |
| 4 | `GET` | `/ready` | Public | `readiness_check` (`backend/app/api/health.py:25-45`) | — | `scripts/smoke_test.py:84`, `infra/nginx/nginx.conf:28` | `test_controller_api_and_services.py:37` | Overlaps with `/api/v1/ready`; returns cluster metadata without auth |
| 5 | `GET` | `/api/v1/ready` | Public | `readiness_check` (`backend/app/api/health.py:26-45`) | — | `scripts/verify_milp_inflight.py:39`, `scripts/verify_rr_isolation.py:39` | — | Overlapping readiness alias |
| 6 | `POST` | `/tasks` | **Public (No API key)** + `ClientRateLimiter` + `_enforce_max_payload_size` | `public_tasks_endpoint` -> `execute_task_contract` (`backend/app/api/tasks.py:646-656`) | `frontend/src/lib/api.ts:142` (`PublicTasksPage.tsx:93,124`) | `tools/load_client.py:90`, `traffic/poisson_generator.py:200`, `scripts/smoke_test.py:137,147`, `scripts/verify_milp_inflight.py:60`, `scripts/verify_rr_isolation.py:71` | `test_admin_and_contracts.py:146,351+`, `test_controller_api_and_services.py:72`, `test_edge_cases_senior_audit.py:288+`, `test_milp_inflight.py:74,115`, `test_round_robin_isolation.py:83+`, `tests/test_shared_contract_suite.py:105+` | Canonical public task submission route; missing from `infra/nginx/nginx.conf` |
| 7 | `POST` | `/api/v1/tasks` | `Depends(verify_api_key)` + `ClientRateLimiter` + `_enforce_max_payload_size` | `submit_task_alias` -> `execute_task_contract` (`backend/app/api/tasks.py:28,659-666`) | **None** | **None** | `test_edge_cases_senior_audit.py:273,281` | **Overlapping alias**; dead in UI/scripts; asymmetric `verify_api_key` vs `POST /tasks` |
| 8 | `POST` | `/api/v1/telemetry` | `Depends(verify_worker_secret)` | `ingest_telemetry` (`backend/app/api/telemetry.py:33-54`) | — | `worker/agent.py:137`, `worker/executor.py:261`, `scripts/smoke_test.py:101` (401 check) | `test_controller_api_and_services.py:44,131`, `test_e2e_cluster_pipeline.py:102`, `test_edge_cases_senior_audit.py:672+`, `test_milp_inflight.py:97`, `test_round_robin_isolation.py:61+` | Worker heartbeat ingestion |
| 9 | `GET` | `/api/v1/telemetry/workers` | `Depends(verify_admin_token)` | `list_workers` (`backend/app/api/telemetry.py:57-64`) | **None** | `scripts/smoke_test.py:92,119` | `test_controller_api_and_services.py:61-62`, `test_edge_cases_senior_audit.py:941` | Unused by frontend (`/ops` uses WS + `/control/snapshot`) |
| 10 | `GET` | `/api/v1/telemetry/redis` | `Depends(verify_admin_token)` | `inspect_redis_state` (`backend/app/api/telemetry.py:67-89`) | **None** | `scripts/smoke_test.py:91,123` | `test_edge_cases_senior_audit.py:494-495,942` | Admin Redis inspection; no UI caller |
| 11 | `GET` | `/api/v1/telemetry/mongo` | `Depends(verify_admin_token)` | `inspect_mongo_state` (`backend/app/api/telemetry.py:92-110`) | **None** | `scripts/smoke_test.py:93` (401 check) | `test_edge_cases_senior_audit.py:501-502,943` | **Exact overlap** with `GET /api/v1/mongo` |
| 12 | `GET` | `/api/v1/mongo` | `Depends(verify_admin_token)` | `get_mongo_data` -> `inspect_mongo_state` (`backend/app/main.py:150-158`) | **None** | **None** | `test_edge_cases_senior_audit.py:301-302,944` | **Dead in UI/scripts & exact duplicate** of `GET /api/v1/telemetry/mongo` |
| 13 | `POST` | `/api/v1/control/scheduler` | `Depends(verify_admin_token)` (router) | `switch_scheduler` (`backend/app/api/control.py:21-51`) | **None** | `scripts/verify_milp_inflight.py:48`, `scripts/verify_rr_isolation.py:52` | `test_admin_and_contracts.py:66,79`, `test_controller_api_and_services.py:88`, `test_round_robin_isolation.py:77`, `tests/test_shared_contract_suite.py:254,269`, `test_edge_cases_senior_audit.py:952` | No UI caller (ops page sets mode via `/admin/test/start`) |
| 14 | `GET` | `/api/v1/control/solver-metrics` | `Depends(verify_admin_token)` (router) | `get_solver_metrics` (`backend/app/api/control.py:54-57`) | **None** | `scripts/verify_milp_inflight.py:67`, `scripts/verify_rr_isolation.py:81` | `test_edge_cases_senior_audit.py:946` | Used by proof/verification CLI checks |
| 15 | `POST` | `/api/v1/control/solver-metrics/reset` | `Depends(verify_admin_token)` (router) | `reset_solver_metrics` (`backend/app/api/control.py:60-64`) | **None** | `scripts/verify_milp_inflight.py:46`, `scripts/verify_rr_isolation.py:47` | **None** | Used by verification scripts only |
| 16 | `POST` | `/api/v1/control/traffic` | `Depends(verify_admin_token)` (router) | `control_traffic` (`backend/app/api/control.py:67-102`) | **None** | **None** | `test_controller_api_and_services.py:97` | **DEAD in UI/scripts (test-only)**; sets unused `paused`/`configured_lambda` |
| 17 | `POST` | `/api/v1/control/workers/{worker_id}/kill` | `Depends(verify_admin_token)` (router) | `kill_worker_node` (`backend/app/api/control.py:105-115`) | **None** | **None** | `test_controller_api_and_services.py:145` | **DEAD in UI/scripts (test-only)** |
| 18 | `POST` | `/api/v1/control/workers/{worker_id}/revive` | `Depends(verify_admin_token)` (router) | `revive_worker_node` (`backend/app/api/control.py:118-130`) | **None** | **None** | `test_controller_api_and_services.py:149` | **DEAD in UI/scripts (test-only)** |
| 19 | `GET` | `/api/v1/control/snapshot` | `Depends(verify_admin_token)` (router) | `get_current_snapshot` (`backend/app/api/control.py:133-137`) | `frontend/src/lib/api.ts:54` (`useWebSocket.ts:90` via `OpsCenterPage.tsx:90`) | `scripts/smoke_test.py:94,124` | `test_controller_api_and_services.py:78-79,111`, `test_e2e_cluster_pipeline.py:146`, `test_edge_cases_senior_audit.py:945` | Not called from `/benchmark` due to `DashboardPage.tsx:8` bug |
| 20 | `GET` | `/api/v1/benchmark/runs` | `Depends(verify_admin_token)` (router) | `list_benchmark_runs` (`backend/app/api/benchmark.py:210-231`) | `frontend/src/lib/api.ts:62` (`BenchmarkSection.tsx:65`) | `scripts/smoke_test.py:95,125` | `test_controller_api_and_services.py:152-153`, `test_edge_cases_senior_audit.py:947` | Triggers synthetic replay if DB empty |
| 21 | `POST` | `/api/v1/benchmark/run` | `Depends(verify_admin_token)` (router) | `trigger_benchmark_run` (`backend/app/api/benchmark.py:234-244`) | `frontend/src/lib/api.ts:75` (`BenchmarkSection.tsx:106`) | — | `test_edge_cases_senior_audit.py:953` (401 check only) | Pollutes global `SOLVER_CALL_COUNT` |
| 22 | `WS` | `/ws` | `verify_admin_ws_token` | `websocket_endpoint` (`backend/app/api/websocket.py:13-29`) | `frontend/src/hooks/useWebSocket.ts:20,23` (`OpsCenterPage.tsx:90`) | `scripts/smoke_test.py:129,131` | `test_controller_api_and_services.py:167,170` | Streams `CLUSTER_SNAPSHOT` every 1.5s |
| 23 | `WS` | `/api/v1/ws` | `verify_admin_ws_token` | `websocket_endpoint` (`backend/app/api/websocket.py:14-29`) | **None** | **None** | **None** | **DEAD / uncalled WS alias** |
| 24 | `POST` | `/admin/auth/login` | Body `token == ADMIN_TOKEN` | `admin_auth_login` (`backend/app/api/admin.py:457-467`) | `frontend/src/lib/api.ts:262` (`AdminAuthContext.tsx:69,95`) | — | `test_edge_cases_senior_audit.py:555-566` | No rate limit on failed attempts |
| 25 | `GET` | `/admin/auth/verify` | `Depends(verify_admin_token)` | `admin_auth_verify` (`backend/app/api/admin.py:470-475`) | `frontend/src/lib/api.ts:269` (`AdminAuthContext.tsx:46`) | — | `test_edge_cases_senior_audit.py:569-573` | Verifies stored `sessionStorage` token |
| 26 | `POST` | `/admin/test/start` | `Depends(verify_admin_token)` | `admin_start_test` (`backend/app/api/admin.py:478-485`) | `frontend/src/lib/api.ts:163` (`OpsCenterPage.tsx:227`) | — | `test_admin_and_contracts.py:101+`, `test_edge_cases_senior_audit.py:99+` | Starts armed->running->draining->idle test |
| 27 | `POST` | `/admin/test/stop` | `Depends(verify_admin_token)` | `admin_stop_test` (`backend/app/api/admin.py:488-493`) | `frontend/src/lib/api.ts:175` (`OpsCenterPage.tsx:257`) | — | `test_admin_and_contracts.py:129`, `test_edge_cases_senior_audit.py:136,140` | Stops active test and triggers summary CSV |
| 28 | `GET` | `/test/status` | **Public** | `get_test_status` (`backend/app/api/admin.py:496-499`) | `frontend/src/lib/api.ts:149` (`OpsCenterPage.tsx:106`) | `tools/load_client.py:31,109` | `test_admin_and_contracts.py:92,356+` | Intentionally public for `load_client.py` sync |
| 29 | `GET` | `/admin/stats/summary` | `Depends(verify_admin_token)` | `get_stats_summary` (`backend/app/api/admin.py:505-515`) | `frontend/src/lib/api.ts:186` (`OpsCenterPage.tsx:152`, `BenchmarkSection.tsx:82`) | `scripts/smoke_test.py:90` | `test_admin_and_contracts.py:244,411`, `test_edge_cases_senior_audit.py:576` | Reads `data/test_summary.csv` |
| 30 | `GET` | `/admin/stats/download` | `Depends(verify_admin_token)` | `download_stats_summary` (`backend/app/api/admin.py:518-545`) | `frontend/src/lib/api.ts:198` (`OpsCenterPage.tsx:277`, `BenchmarkSection.tsx:124`) | — | `test_admin_and_contracts.py:249,252`, `test_edge_cases_senior_audit.py:77,81,578-579` | Serves `test_summary.csv` or `test_log.csv` |
| 31 | `GET` | `/admin/stats/live` | `Depends(verify_admin_token)` | `get_live_dispatch_stats` (`backend/app/api/admin.py:548-555`) | `frontend/src/lib/api.ts:237` (`OpsCenterPage.tsx:114,179`) | — | `test_edge_cases_senior_audit.py:482,577` | Live 60s dispatch chart series |
| 32 | `POST` | `/admin/stats/reset` | `Depends(verify_admin_token)` | `reset_stats` (`backend/app/api/admin.py:558-576`) | `frontend/src/lib/api.ts:248` (`OpsCenterPage.tsx:298`) | — | `test_admin_and_contracts.py:239`, `test_edge_cases_senior_audit.py:85,133,580` | Archives CSVs and resets live stats |

---

## 2. Conditional SPA & Static Routes (`backend/app/main.py:162-190`)

Mounted only when `frontend/dist/assets` is a directory and `frontend/dist/index.html` is a file:

| Method | Path | Auth | Handler (`file:line`) | Caller Evidence | Notes |
|---|---|---|---|---|---|
| `MOUNT` | `/assets` | Public | `StaticFiles(directory=str(assets_dir))` (`main.py:165-169`) | `<script>`/`<link>` in `frontend/dist/index.html` | Serves Vite JS/CSS bundle (`index-1KXRepmu.js`, `index-CYLeEu4u.css`) |
| `GET` | `/` | Public HTML | `serve_dashboard_spa` (`main.py:171-173`) | `scripts/smoke_test.py:156` | Renders `PublicTasksPage` |
| `GET` | `/ops` | Public HTML (client `<AdminAuthGate>`) | `serve_ops_spa` (`main.py:175-177`) | `scripts/smoke_test.py:156` | Renders `<AdminAuthGate><OpsCenterPage /></AdminAuthGate>` |
| `GET` | `/admin` | Public HTML (client `<AdminAuthGate>`) | `serve_admin_spa` (`main.py:179-181`) | **None in backend scripts/tests** | Client router (`App.tsx:33-38`) redirects to `/ops` inside `<AdminAuthGate>` |
| `GET` | `/benchmark` | Public HTML (client `<AdminAuthGate>`) | `serve_benchmark_spa` (`main.py:183-185`) | `frontend/src/__tests__/App.test.tsx:215` | Renders `<AdminAuthGate><DashboardPage /></AdminAuthGate>` |
| `GET` | `/client` | Public `307` | `serve_client_spa` (`main.py:187-189`) | `frontend/src/__tests__/App.test.tsx:166` | 307 redirects to `/` |

---

## 3. Worker Process Routes (`worker/executor.py`, ports `8001-8003`)

Separate FastAPI ASGI app (`create_worker_app` at `worker/executor.py:233-526`) intended for private/local network only:

| Method | Path | Auth Enforced | Handler (`file:line`) | Callers |
|---|---|---|---|---|
| `GET` | `/health` | **None** | `health` (`worker/executor.py:312-324`) | `scripts/verify_worker_b1.py:20`, `test_traffic_and_worker.py:138` |
| `GET` | `/status` | **None** | `status_endpoint` (`worker/executor.py:326-344`) | `test_worker_queue_and_limits.py:42,130` |
| `GET` | `/metrics` | **None** | `metrics` (`worker/executor.py:346-364`) | `test_traffic_and_worker.py:162` |
| `POST` | `/execute` | **None** | `execute_workload` (`worker/executor.py:366-525`) | `backend/app/api/tasks.py:450,453`, `scripts/verify_worker_b1.py:49+`, `test_worker_*.py` |

---

## 4. Flagged Issues (Dead, Overlapping & Broken Wiring)

1. **Completely dead routes (zero callers anywhere in codebase):**
   - `GET /api/v1/health` (`backend/app/api/health.py:19`)
   - `WS /api/v1/ws` (`backend/app/api/websocket.py:14`)
2. **Test-only / UI-dead routes (no frontend or operational script callers):**
   - `GET /api/v1/mongo` (`backend/app/main.py:150-158`) — exact duplicate of `GET /api/v1/telemetry/mongo` (`telemetry.py:92`).
   - `POST /api/v1/control/traffic` (`backend/app/api/control.py:67`) — mutates unused `scheduler_state.paused` / `configured_lambda` and injects spikes.
   - `POST /api/v1/control/workers/{worker_id}/kill` (`backend/app/api/control.py:105`) and `.../revive` (`control.py:118`).
   - `POST /api/v1/tasks` (`backend/app/api/tasks.py:659-666`) — only called in `test_edge_cases_senior_audit.py:273,281`; overlaps `POST /tasks` with asymmetric auth (`Depends(verify_api_key)` present on `/api/v1/tasks`, absent on `/tasks`).
3. **Overlapping route groups:**
   - Health: `/health`, `/healthz`, `/api/v1/health` (`health.py:17-19`)
   - Readiness: `/ready`, `/api/v1/ready` (`health.py:25-26`)
   - Mongo inspection: `/api/v1/mongo` (`main.py:150`) and `/api/v1/telemetry/mongo` (`telemetry.py:92`)
   - Tasks: `POST /tasks` and `POST /api/v1/tasks` (`tasks.py:646,659`)
   - WebSocket: `WS /ws` and `WS /api/v1/ws` (`websocket.py:13-14`)
4. **BUG — `DashboardPage` (`/benchmark`) never connects to `/ws` or `/api/v1/control/snapshot` (`frontend/src/pages/DashboardPage.tsx:8-9`):**
   - `DashboardPage.tsx:8` invokes `useWebSocket()` with zero arguments (defaulting `token = null`). In `frontend/src/hooks/useWebSocket.ts:107-112`, `!token` forces `connectionState = "DISCONNECTED"` and aborts WebSocket connection and `fetchSnapshotFallback`. Thus the header on `/benchmark` is permanently `DISCONNECTED` with `0.0 req/s` / `OR-Tools MILP` static defaults.
5. **BUG — `infra/nginx/nginx.conf` breaks core routes in Docker/Nginx deployments (`infra/nginx/nginx.conf:14-47`):**
   - Nginx only proxies `/api/`, `/health`, `/ready`, and `/ws`. Paths `/tasks`, `/admin/*`, `/test/status`, and `/healthz` fall into `location / { try_files $uri $uri/ /index.html; }` (`nginx.conf:45-47`), breaking task submission and admin operations behind Nginx/Docker Compose.
