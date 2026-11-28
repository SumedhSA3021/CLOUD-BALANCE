# 05 — Hardcoded Values & Configuration Drift Audit

**Goal:** Find all hardcoded `localhost`, `127.0.0.1`, ports `8000-8003`, worker IDs, tokens, secrets, timeouts, and absolute paths in `backend/`, `worker/`, `frontend/src/`, `tools/`, `traffic/`, `scripts/`, and deployment configs that are not driven by `.env`/config.  
**Verdict:** **WARN / FAIL** — Local `.env`-based tunnel deployment (`backend/run_cluster.py` + Cloudflare tunnel) avoids hardcoded URLs in the React SPA (`frontend/src/lib/api.ts:8` `""`, `useWebSocket.ts:22-23` `window.location`), **but** multiple hardcoded worker IDs/timeouts/API-key defaults remain in runtime code, `backend/.env` shadows root `.env`, `traffic/cli.py` and `verify_worker_b1.py` lack env overrides, and `docker-compose.yml` + `infra/*` are out of sync with required secrets and routes.

---

## 1. Non-Overridable Hardcoded Values in Runtime / UI / Scripts

| File & Line | Hardcoded Value | Driven by `.env` / Config? | Impact |
|---|---|---|---|
| `backend/app/api/admin.py:323` | `("worker-1", "worker-2", "worker-3")` | **No** | Draining loop skips any custom worker IDs or 4+ workers from `WORKER_URLS` |
| `backend/app/schedulers/test_hooks.py:23` | `WORKERS = ("worker-1", "worker-2", "worker-3")` | **No** | `start_test`/`reset_redis_test_keys` only reset Redis `inflight:*` for those 3 IDs |
| `backend/app/core/live_stats.py:10, 21, 24-28, 79-95` | `WORKERS = ("worker-1", "worker-2", "worker-3")` | **No** | Silently drops live chart dispatches for any other `worker_id` (`live_stats.py:32`) |
| `backend/app/core/logger.py:364, 369, 374, 399-401` | `"worker-1"`, `"worker-2"`, `"worker-3"` -> `worker1_busy_ms..worker3_busy_ms` | **No** | Summary CSV schema & calculation fixed to 3 named workers |
| `frontend/src/pages/OpsCenterPage.tsx:56, 340-342, 378-395, 755` | `WORKER_NAMES = ["worker-1", "worker-2", "worker-3"]`; `"Limit: 2 simultaneous"` | **No** | Worker cards, charts, and concurrency text ignore dynamic `snapshot.workers` |
| `frontend/src/components/Header.tsx:53` | Fallback scheduler string `"OR-Tools MILP"` | **No** | Displays `OR-Tools MILP` while `snapshot == null`, even if cluster runs RR |
| `backend/app/api/tasks.py:452` | `httpx.AsyncClient(timeout=15.0)` | **No** | Ignores `Settings.dispatch_timeout_sec` (`config.py:201`, default `12.0`); recreates client per request |
| `backend/app/api/tasks.py:25` | `WORKERS = [ep.worker_id for ep in parse_worker_endpoints(DEFAULT_WORKER_URLS)]` | **No** | Unused module constant hardcoded to 3 default workers |
| `backend/app/api/tasks.py:139` | `return "http://127.0.0.1:8001/execute"` | **No** | Defensive fallback if endpoints list somehow empty |
| `backend/app/core/config.py:111-114` | `api_key: str = Field(default="cb-dev-api-key-2026", ...)` | Default present | Fallback hardcoded dev secret if `CB_REQUIRE_API_KEY=true` without `CB_API_KEY` |
| `backend/app/services/cluster_state.py:17-21` | `_VIRTUAL_PROFILES = ((12.5, 4096, 640, ...), (18.0, ...), (9.0, 8192, ...))` | **No** | Hardcoded virtual telemetry profiles |
| `backend/run_cluster.py:19-23, 59-62, 151, 164` | `_WORKER_PROFILES`, `WORKER_TIME_SCALE="0.55"`, `WORKER_MAX_PHYSICAL_DIM="450"`, `CB_SEED_DEMO_WORKERS="false"`, `--host 0.0.0.0` | **No** | Overrides `.env`'s `CB_SEED_DEMO_WORKERS` (`run_cluster.py:151`) and worker timing tuning |
| `backend/app/api/benchmark.py:76-80, 102-103` | `worker-1..3`, `ip_address="10.128.0.10"`, `port=8001`, fixed CPUs | **No** | Synthetic benchmark ignores cluster config |
| `scripts/verify_worker_b1.py:15` | `worker_url = "http://127.0.0.1:8001"` | **No** | No CLI flag or env override |
| `traffic/cli.py:24` | `default="http://localhost:8000"` | CLI `--target-url` only (**no env var**) | Does not honor `CB_BASE_URL` / `CONTROLLER_URL` |

---

## 2. Deployment / Infra Hardcodes & Drift (`docker-compose.yml`, `infra/`)

| File & Line | Finding | Severity |
|---|---|---|
| `docker-compose.yml:30-100` | Missing `ADMIN_TOKEN`, `WORKER_SECRET`, `WORKER_URLS`; hardcodes `CB_API_KEY="${CB_API_KEY:-cb-dev-api-key-2026}"`, `cb-redis-local-pass`, ports `8000..8003` | **FAIL** — Controller container refuses to start (`Settings` requires `ADMIN_TOKEN` + `WORKER_SECRET`) |
| `infra/gcp/startup-controller.sh:12-29` | Missing `ADMIN_TOKEN`, `WORKER_SECRET`, `WORKER_URLS`; hardcodes `127.0.0.1:6379`; fallbacks `"cb-redis-pass"`, `"cb-api-key"` | **FAIL** — GCP controller refuses to start |
| `infra/gcp/startup-worker.sh:14-24` | Missing `WORKER_SECRET`; fallback `"http://10.128.0.10:8000"`; hardcodes `WORKER_PORT=8001` | **FAIL** — GCP workers get `401` on `POST /api/v1/telemetry` |
| `infra/gcp/provision.sh:22-24, 75, 86, 119` | Hardcodes VPC `10.128.0.10..12`, port `8000`/`8001`, 2 workers instead of 3, does not pass `admin-token` / `worker-secret` metadata | **FAIL** |
| `infra/nginx/nginx.conf:15,25,29,34` | Hardcodes `http://controller:8000` AND **omits** `/tasks`, `/admin/`, `/test/`, `/healthz` | **FAIL** |
| `infra/systemd/*.service` | Hardcodes `/opt/cloudbalance`, `/etc/cloudbalance`, `--port 8000`, `--port 8001` | Expected VM unit paths (rigid) |

---

## 3. Overridable Defaults, `.env` Shadowing & Dead Config Fields

### Overridable Defaults (Cleanly Config-Driven)
- `backend/app/core/config.py:16-20, 102, 125, 129`: `DEFAULT_WORKER_URLS` (`127.0.0.1:8001..8003`), `controller_url` (`127.0.0.1:8000`), `redis_url` (`localhost:6379/0`), `mongo_url` (`mongodb://localhost:27017`) — all overridable via `.env`.
- `worker/executor.py:71-72, 237` & `worker/agent.py:98, 165-170`: `127.0.0.1`, `8001`, `127.0.0.1:8000` / `localhost:8000` — all overridable via `WORKER_IP`, `WORKER_PORT`, `CONTROLLER_URL`, `WORKER_SECRET`.
- `frontend/vite.config.ts:10-30`: `http://localhost:8000` / `ws://localhost:8000` — dev proxy only, overridden by `VITE_API_TARGET` / `VITE_WS_TARGET`.
- `frontend/src/lib/api.ts:8` & `frontend/src/hooks/useWebSocket.ts:14-24`: `API_BASE = import.meta.env.VITE_API_BASE_URL || ""` (relative origin at runtime) and `ws:`/`wss:` derived dynamically from `window.location`. Raw scan of `frontend/dist/assets/index-1KXRepmu.js` shows **zero** `localhost`, `127.0.0.1`, or `:8000` URLs (`8000` matches only hex color `"800000"`/`"808000"`).
- `tools/load_client.py:219` & `scripts/smoke_test.py:62` & `scripts/verify_*.py:32`: Overridable via `CB_BASE_URL` / `CONTROLLER_URL` / `--controller`.
- **Absolute filesystem paths in Python/TS source:** **None found** (`ROOT_DIR`, `ROOT_ENV_FILE`, `FRONTEND_DIST_DIR` all use `Path(__file__).resolve()`).

### `.env` Precedence & Dead Settings Hazards
1. **Stale `backend/.env` overrides root `.env` (`backend/app/core/config.py:74-75` + `backend/.env`):**
   - `config.py:75` sets `env_file=(str(ROOT_ENV_FILE), ".env")`.
   - File `backend/.env` currently exists and contains `CB_LOCAL_MODE="true"`. When running uvicorn with CWD=`backend/`, `.env` in CWD takes precedence over `ROOT_ENV_FILE`, silently overriding root `.env`'s `CB_LOCAL_MODE`!
2. **Dead / unread `Settings` fields (`backend/app/core/config.py`):**
   - `rate_limit_per_sec` (`152`), `max_queue_depth` (`147`), `batch_window_ms` (`171`), `batch_max_size` (`177`), `dispatch_timeout_sec` (`201`), `dispatch_max_retries` (`206`), `data_dir` (`167` — `logger.py:26` reads `os.getenv` directly instead of `Settings`), `controller_url` (`101`), `controller_port` (`105`), `environment` (`85`).
