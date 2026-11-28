# 06 — Auth Matrix, Leaks & Secret Hygiene Audit

**Goal:** Compare expected vs actual auth on every route, flag cluster-info leaks, check default secrets, check git-tracked secrets, and verify `.env` is gitignored.  
**Verdict:** **FAIL / WARN** — Core `/admin/*`, `/api/v1/control/*`, `/api/v1/benchmark/*`, `/api/v1/telemetry/*`, and `/ws` are locked down with `ADMIN_TOKEN` / `WORKER_SECRET` and no `ADMIN_TOKEN`/`WORKER_SECRET` defaults exist in `Settings`, **but** (1) `POST /tasks` vs `POST /api/v1/tasks` disagree on `verify_api_key`, (2) `GET /ready` and `POST /tasks` leak internal cluster info, (3) `Settings.api_key` still has a hardcoded default `"cb-dev-api-key-2026"`, (4) WS sends `ADMIN_TOKEN` in URL query string, (5) `Local-Version/` (tracked in git) still holds committed default secrets `"cb-admin-secret-2026"` & `"cb-dev-api-key-2026"`, and (6) root `backend/`, `frontend/`, `worker/` are **untracked** due to `.gitignore`!

---

## 1. Expected vs Actual Auth Matrix

| Route / Endpoint | Expected Auth | Actual Auth (`file:line`) | Match? | Security / Leak Notes |
|---|---|---|---|---|
| `GET /health`, `/healthz`, `/api/v1/health` | Public | Public (`health.py:17-22`) | **PASS** | Returns only `status` and `service` |
| `GET /ready`, `/api/v1/ready` | Public (minimal readiness) | Public (`health.py:25-45`) | **WARN** | **Info leak:** exposes `redis_backend`, `persistence_backend`, `active_workers` count, `active_scheduler`, `queue_depth` |
| `GET /test/status` | Public (for `load_client.py`) | Public (`admin.py:496-499`) | **PASS** | Reveals active test metadata & counts while running |
| `POST /tasks` | Public (optionally API-key gated if configured) | **Unconditionally Public** — `ClientRateLimiter` + payload limit (`tasks.py:646-656`); **no `verify_api_key`!** | **WARN / FAIL** | Bypass vector if `CB_REQUIRE_API_KEY=true`; response reveals `assigned_worker`, `scheduler_used`, `dispatch_seq`, and `port {worker_port}` on offline error (`tasks.py:555`) |
| `POST /api/v1/tasks` | Same as `POST /tasks` | `Depends(verify_api_key)` (`tasks.py:659-666`) | **INCONSISTENT** | `verify_api_key` applied here but omitted on `/tasks` |
| `POST /api/v1/telemetry` | `X-Worker-Secret` / Bearer `WORKER_SECRET` | `Depends(verify_worker_secret)` (`telemetry.py:37`) | **PASS** | Constant-time `secrets.compare_digest` (`security.py:132`) |
| `GET /api/v1/telemetry/workers` | Admin Bearer | `Depends(verify_admin_token)` (`telemetry.py:60`) | **PASS** | — |
| `GET /api/v1/telemetry/redis` | Admin Bearer | `Depends(verify_admin_token)` (`telemetry.py:70`) | **PASS** | Fixed from earlier audit |
| `GET /api/v1/telemetry/mongo` | Admin Bearer | `Depends(verify_admin_token)` (`telemetry.py:95`) | **PASS** | — |
| `GET /api/v1/mongo` | Admin Bearer | `Depends(verify_admin_token)` (`main.py:153`) | **PASS** | Duplicate route |
| `POST /api/v1/control/*` & `GET .../snapshot`, `solver-metrics` | Admin Bearer | Router `Depends(verify_admin_token)` (`control.py:24`) | **PASS** | — |
| `GET /api/v1/benchmark/runs`, `POST /api/v1/benchmark/run` | Admin Bearer | Router `Depends(verify_admin_token)` (`benchmark.py:28`) | **PASS** | — |
| `POST /admin/auth/login` | Admin Token validation | Body `secrets.compare_digest` (`admin.py:457-467`) | **WARN** | **No rate limit / brute-force lockout** on failed logins |
| `GET /admin/auth/verify` | Admin Bearer | `Depends(verify_admin_token)` (`admin.py:472`) | **PASS** | — |
| `POST /admin/test/start`, `stop`, `stats/reset`; `GET /admin/stats/summary`, `download`, `live` | Admin Bearer | `Depends(verify_admin_token)` (`admin.py:482-560`) | **PASS** | All protected |
| `WS /ws`, `WS /api/v1/ws` | Admin Token | `verify_admin_ws_token` (`websocket.py:17`, `security.py:106-117`) | **WARN** | Rejects anonymous (`1008`); **token passed in URL `?token=`** (`useWebSocket.ts:27`) risks proxy/access-log leakage |
| `GET /`, `/ops`, `/admin`, `/benchmark`, `/client`, `/assets/*` | Public static SPA | Public static files (`main.py:165-189`) | **PASS** | `/ops`, `/admin`, `/benchmark` gated client-side by `<AdminAuthGate>` + all data APIs return `401` |
| Worker `:8001-8003` (`POST /execute`, `GET /health`, `/status`, `/metrics`) | Internal/VPC-isolated (or worker auth) | **None** (`worker/executor.py:312-367`) | **WARN** | Relies strictly on firewall/`127.0.0.1` binding (`entrypoint.sh:11` & systemd bind `0.0.0.0:8001`) |

---

## 2. Cluster-Info Leaks & Session Security Checks

1. **`GET /ready` (`backend/app/api/health.py:38-45`):** Exposes `redis_backend` (`in_memory_ttl`/`redis`), `persistence_backend` (`sqlite_fallback`/`mongodb`), `active_workers`, `active_scheduler`, `queue_depth` without auth.
2. **`POST /tasks` error & metadata (`backend/app/api/tasks.py:555, 641-642`):** Returns internal `assigned_worker` (intended for portal display), `scheduler_used`, `dispatch_seq`, and leaks internal port on worker offline (`f"Worker {assigned_worker} offline or unreachable on port {worker_port}"`).
3. **WS `?token=` query string (`frontend/src/hooks/useWebSocket.ts:27`):** `ADMIN_TOKEN` is appended to URL `?token=...`, exposing it to browser history and reverse-proxy/Cloudflare/uvicorn logs.
4. **`sessionStorage` persistence (`frontend/src/context/AdminAuthContext.tsx:11,70`):** Raw `ADMIN_TOKEN` stored in browser `sessionStorage` with no server-issued short-lived HMAC/JWT session cookie.

---

## 3. Default Secrets, `.gitignore`, and Git-Tracked Secrets Evidence

### Startup Enforcement Check (`backend/app/core/config.py:89-96, 228-235`)
- `ADMIN_TOKEN` (`admin_token: str = Field(...)`) and `WORKER_SECRET` (`worker_secret: str = Field(...)`) have **no defaults** and fail Pydantic validation on empty/whitespace (`config.py:228-235`).
- Verified active `.env` (via PowerShell check):
  ```text
  ADMIN_TOKEN present=True len=27 weak_or_placeholder=False
  WORKER_SECRET present=True len=28 weak_or_placeholder=False
  ```
- **Remaining hardcoded secrets:**
  1. `backend/app/core/config.py:112`: `api_key: str = Field(default="cb-dev-api-key-2026", ...)` (**hardcoded default API key**).
  2. `docker-compose.yml:5,9,34,36,61,80,99`: fallbacks `"cb-redis-local-pass"` and `"cb-dev-api-key-2026"`.
  3. `infra/gcp/startup-controller.sh:12-13`: fallbacks `"cb-redis-pass"` and `"cb-api-key"`.
  4. `conftest.py:8-9`: pytest-only env defaults `"cb-admin-test-token"` / `"cb-worker-test-secret"`.

### `.gitignore` & `git grep` Output
Raw command output:
```text
> git check-ignore -v .env backend/.env .env.example Local-Version/.env
.gitignore:2:.env	.env
.gitignore:48:/backend/	backend/.env
.gitignore:55:/.env.example	.env.example
Local-Version/.gitignore:2:.env	Local-Version/.env

> git ls-files "*env*"
Local-Version/.env.example
Local-Version/frontend/src/vite-env.d.ts

> git grep -n "cb-admin\|cb-worker\|cb-dev-api-key" -- ":!audit"
Local-Version/backend/app/api/admin.py:46:ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "cb-admin-secret-2026")
Local-Version/backend/app/core/config.py:31:        default="cb-dev-api-key-2026",
Local-Version/backend/tests/test_admin_and_contracts.py:35:ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "cb-admin-secret-2026")
Local-Version/docker-compose.yml:34:      CB_API_KEY: "${CB_API_KEY:-cb-dev-api-key-2026}"
... (repeated on lines 61, 80, 99 of Local-Version/docker-compose.yml)
```
- **`.env` gitignored?** **PASS** (`.env`, `backend/.env`, and `Local-Version/.env` are all ignored and untracked).
- **Secrets in git-tracked files?** **FAIL** — `Local-Version/` (which is tracked in git) has `"cb-admin-secret-2026"` (`Local-Version/backend/app/api/admin.py:46`, `test_admin_and_contracts.py:35`) and `"cb-dev-api-key-2026"` (`Local-Version/backend/app/core/config.py:31`, `Local-Version/docker-compose.yml:34,61,80,99`) in the tracked commit/index!
- **Repo-tracking anomaly:** `.gitignore:48-57` ignores root `/backend/`, `/frontend/`, `/worker/`, `/traffic/`, `/infra/`, `/.env.example`, `/docker-compose.yml`, `/Makefile` — meaning NONE of the root hardened code is currently tracked in git!
