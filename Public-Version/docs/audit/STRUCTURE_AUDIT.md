# CloudBalance Structure, Architecture & GCP Deploy-Readiness Audit (Phase 1)

**Audit Scope:** Read-only structural & deploy-readiness analysis (`audit/STRUCTURE_AUDIT.md` only). Zero code, config, `.gitignore`, or `Local-Version/` changes applied.  
**Snapshot Baseline:** Git branch `pre-structure-pass` (`ecd6ae0`), external zip `C:\Users\sumed\cloudbalance-snapshots\pre-structure-pass.zip` (`421` files), `pytest=71`, `vitest=11`, `tsc=0`, `ruff=0` (active scope), `smoke_test`/`verify_rr_isolation`/`verify_milp_inflight` PASS.

---

## Executive Answers (Pre-Phase Checks 1–4)

### 1. Git History Secret Exposure Check
- **Live `.env`:** `git log --all --oneline -- .env` returned **empty (`0` commits)** — the live `.env` file never reached git or `origin/main`. `WORKER_SECRET` also has **`0` commits** across all git history.
- **Older fallback secrets DID reach `origin/main` inside `Local-Version/`:** Across the `27` commits (`ecd6ae0` on `origin/main` and earlier commits like `52d13aa`), git history contains:
  - `Local-Version/backend/app/api/admin.py:43`: `ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "cb-admin-secret-2026")`
  - `Local-Version/backend/tests/test_admin_and_contracts.py:38`: `"cb-admin-secret-2026"`
  - `Local-Version/backend/app/core/config.py:31` & `Local-Version/docker-compose.yml:34,61,80,99`: `"cb-dev-api-key-2026"`
  - Earlier commit `52d13aa`: `Local-Version/frontend/src/pages/OpsCenterPage.tsx:54` & `BenchmarkSection.tsx:46` (`"cb-admin-secret-2026"`), plus compiled JS in `Local-Version/frontend/dist/`.
- **Active root source (`backend/`, `frontend/src/`, `worker/`):** Zero hardcoded `ADMIN_TOKEN` or `WORKER_SECRET` fallbacks (startup fails if unset per `backend/app/core/config.py:89-96, 228-235`). Only `Settings.api_key` defaults to `"cb-dev-api-key-2026"` (`config.py:112`, inactive while `CB_REQUIRE_API_KEY=false`), and root `docker-compose.yml:5,34-99` still sets `${CB_API_KEY:-cb-dev-api-key-2026}` and `${REDIS_PASSWORD:-cb-redis-local-pass}` defaults.
- **Remediation:** Rotate any token previously used in `Local-Version/` (`ADMIN_TOKEN`, `CB_API_KEY`), remove or archive `Local-Version/` from active tracking in Phase 2 (after approval), and purge/squash history only if rewriting public git history is desired later.

### 2. Recommendation on `frontend/dist/`
- **Recommendation: Ignore `frontend/dist/` in `.gitignore` and build on the Controller VM (or inside the Docker multi-stage build).**
- **Why:**
  1. Prevents binary/hash churn (`index-Z-OLQV_M.js`) and merge conflicts in git.
  2. Prevents stale UI bundles being deployed when `frontend/src/` changes (already observed inside `Local-Version/frontend/dist/`).
  3. Matches clean CI/fresh-clone parity (`npm ci && npm run build`) verified in Phase 4. *(Requires Node `>=20` on the Controller VM or Docker build stage.)*

### 3. `Local-Version/` & `Public-Version/`
- **`Local-Version/` (`118` files; `112` git-tracked + uncommitted local edits/untracked files):** An earlier frozen snapshot of CloudBalance from before Phase 0–4 refactorings. Diff against root: **`58` byte-identical**, **`48` diverged** (`backend/app/api/admin.py`, `tasks.py`, `logger.py`, `config.py`, `frontend/src/*`), and **`12` deleted-from-root legacy files** (`batcher.py`, `dispatcher.py`, `least_connections.py`, `ClientPage.tsx`, `WorkerCard.tsx`, `ControlPanel.tsx`, `MetricsChart.tsx`, `AssignmentFeed.tsx`, `ClientPanel.tsx`, `verify_worker_b2_flood.py`, plus `dist/assets/`).
- **`Public-Version/` (`1` file):** Empty placeholder folder containing only `.gitkeep`.
- **References/Imports:** Nothing in active source (`backend/`, `worker/`, `frontend/src/`, `tools/`, `traffic/`, `scripts/`, `tests/`) imports from `Local-Version/` or `Public-Version/`. Only [README.md](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/README.md#L7-L31) and [pyrightconfig.json](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/pyrightconfig.json#L10-L18) reference them.
- **Proposal (awaiting approval before touching):** Move `Local-Version/` and `Public-Version/` out of active git paths (archive outside active tree / move to `archive/` after user sign-off) and keep ONE source of truth at repository root.

### 4. Simulated `git status --ignored` With Proposed `.gitignore`
Tested in an isolated temporary git repository without editing the workspace `.gitignore`:
- **Would be tracked (`??`):** `backend/` (`backend/app/*`, `backend/tests/*`, `backend/run_cluster.py`, `pyproject.toml`, `Dockerfile`), `frontend/` (`src/`, `package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`, `Dockerfile`), `worker/`, `tools/`, `traffic/`, `benchmark/`, `infra/`, `scripts/`, `tests/`, `audit/`, `proof/`, `conftest.py`, `pytest.ini`, `pyrightconfig.json`, `.env.example`, `docker-compose.yml`, `Makefile`, `README.md`, `.github/`.
- **Would be ignored (`!!`):** `.env`, `backend/.env`, `data/`, `frontend/dist/`, `frontend/node_modules/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `backend/.coverage`, `*.log` (`cluster_run.log`, `cluster_startup.log`, `run_cluster.log`), `*.zip` (`CloudBalance.zip`, `pre-client-page.zip`).
  *(Note: `git check-ignore -v .env.example` prints negation line `!.env.example` and exits `0` by design, while `git status --ignored -s` classifies `.env.example` under untracked `??` ready to commit.)*

---

## 1. Repository Tree & Ownership Map (`424` non-cache files)

| Path | Count | Role / Owner | Notes / Flags |
|---|---:|---|---|
| `backend/app/main.py` | 1 | Controller FastAPI factory, lifespan, CORS, SPA mount | Core controller owner |
| `backend/app/api/` | 8 | Route modules (`tasks`, `admin`, `benchmark`, `control`, `health`, `telemetry`, `websocket`) | `control.py` + parts of `benchmark.py` overlap |
| `backend/app/core/` | 9 | Config, CSV logger, structlog setup, profiles, DualRedis/Mongo, security, simulator | `backend/.env` shouldn't live inside `backend/` |
| `backend/app/models/` | 2 | Pydantic schemas (`Task`, `Telemetry`, `ClusterSnapshot`, requests) | Clean |
| `backend/app/schedulers/` | 5 | `base.py`, `ortools_milp.py`, `round_robin.py`, `test_hooks.py` | `round_robin.py` unused in runtime `/tasks` |
| `backend/app/services/` | 6 | `broadcaster.py`, `client_stats.py`, `cluster_state.py`, `history.py`, `scheduler_state.py` | Clean separation |
| `backend/tests/` | 13 | Primary pytest suite (`test_*.py`) | Overlaps root `tests/test_shared_contract_suite.py` |
| `backend/run_cluster.py`, `Dockerfile`, `pyproject.toml` | 3 | Local cluster launcher, controller container, Python package spec | Also leftover `backend/.env`, `backend/.coverage` |
| `worker/` | 6 | `executor.py`, `agent.py`, `entrypoint.sh`, `Dockerfile`, `requirements.txt`, `__init__.py` | Independent worker runtime |
| `frontend/` | 30 | React 18 + TS + Tailwind + Vitest SPA (`PublicTasksPage`, `ClientLoadPage`, `OpsCenterPage`, `DashboardPage`) | Includes build artifact `frontend/dist/` |
| `tools/load_client.py` | 1 | External Poisson benchmark client CLI (3-laptop harness) | Active |
| `traffic/` | 5 | Legacy `cb-traffic` CLI (`cli.py`, `poisson_generator.py`, `workloads.py`, `pyproject.toml`) | Calls `/api/v1/tasks`; overlaps `tools/load_client.py` |
| `scripts/` | 6 | `run_local.ps1`, `run_local.sh`, `smoke_test.py`, `verify_rr_isolation.py`, `verify_milp_inflight.py`, `verify_worker_b1.py` | Mixed tracked (`3`) vs untracked (`3`) |
| `tests/` | 2 | `__init__.py`, `test_shared_contract_suite.py` (`273L`) | Exact near-duplicate of `backend/tests/test_shared_contract_suite.py` |
| `benchmark/` | 6 | `run_benchmark.py` + `results/*` plots/CSVs | **Broken import** (`LeastConnectionsScheduler`) |
| `infra/` | 8 | `gcp/{provision,startup-controller,startup-worker,teardown}.sh`, `nginx/nginx.conf`, `systemd/*.service` | Outdated for current secrets & `/tasks`, `/admin/`, `/client` |
| `.github/workflows/ci.yml` | 1 | GitHub Actions CI (`ruff`, `mypy`, `pytest`, `benchmark`, `tsc`, `vitest`, `build`) | Runs `benchmark/run_benchmark.py` (currently fails) |
| `data/` | 59 | Runtime `test_log.csv`, `test_summary.csv`, `archive/*.csv`, SQLite fallbacks | Runtime data; should stay ignored |
| `audit/` & `proof/` | 10 | Prior Phase/Audit markdown reports (`01..07`, `STATIC_AUDIT_REPORT.md`, `PROOF_REPORT.md`) | Historical evidence docs |
| `Local-Version/` | 118 | Frozen pre-refactor mirror + legacy modules | Legacy copy; untouchable before explicit approval |
| `Public-Version/` | 1 | `.gitkeep` only | Unowned empty placeholder |
| `01_Documentation_And_Reports/` & `local draft one/` | 102 | Academic project docs, diagrams, draft member packages | Archive docs, no runtime code dependency |
| Root artifacts | 18 | `.env`, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, `README.md`, `Makefile`, `docker-compose.yml`, `pytest.ini`, `conftest.py`, `pyrightconfig.json`, `CloudBalance.zip`, `pre-client-page.zip`, `*.log`, `.coverage`, `CHANGES_AND_UPGRADE_TASK_SHEET.md`, `CloudBalance_Team_Workflow.html` | Several stale logs/zips/coverage files |

---

## 2. Duplicates & Stale Files Inventory

| Item / Path | What It Duplicates / Role | Recommended Action (Phase 2, after approval) | Risk |
|---|---|---|---|
| `backend/tests/test_shared_contract_suite.py` vs `tests/test_shared_contract_suite.py` | Only whitespace diff (1 blank line on line 20); causes 3 tests to run twice (`6` vs `3`) | **Keep** `backend/tests/test_shared_contract_suite.py` (update `pytest.ini` `testpaths`) OR **move** root `tests/test_shared_contract_suite.py` to `archive/` after approval — note baseline count drops by 3 unless accounted for (`71 - 3 = 68 < 71`, so **replace with >=3 non-duplicate unit tests or keep `testpaths = backend/tests` carefully!**) | MED |
| `Local-Version/` (`118` files) | Outdated copy of root `backend/`, `frontend/`, `worker/`, `infra/`, `scripts/`, `tools/`, `traffic/` (`58` identical, `48` stale) | **Do not delete silently:** propose moving/removing from active tree after approval (kept in git history tag/branch `pre-structure-pass`) | MED |
| `Public-Version/` (`.gitkeep`) | Unused placeholder folder (`1` file) | **Move to `archive/` or delete** after approval | LOW |
| `backend/.env` (`CB_LOCAL_MODE`) | Partial `.env` inside `backend/` that overrides when running from `backend/` | **Archive / remove** (keep single root `.env` only) | LOW |
| `.coverage`, `backend/.coverage` | Stale coverage binaries | **Move to `archive/` or remove** (already ignored cleanly) | LOW |
| `CloudBalance.zip`, `pre-client-page.zip` | In-repo zip archives (`pre-structure-pass.zip` already stored safely outside at `C:\Users\sumed\cloudbalance-snapshots\`) | **Move to `archive/`** (keep out of repo git) | LOW |
| `cluster_run.log`, `cluster_startup.log`, `run_cluster.log` | Stale local stdout logs | **Move to `archive/`** | LOW |
| Root `"worker-1", "worker-2", "worker-3"` literals | Repeated in `admin.py:323`, `test_hooks.py:23`, `live_stats.py:10,21`, `logger.py:384-396`, `benchmark.py:76,112`, `OpsCenterPage.tsx:56` | **Keep behavior unchanged now**; note for future dynamic-worker support (low risk consolidation only via `Settings.worker_endpoints()` helper) | MED |
| Scratch files (`phase4_*.py`) | None in repo! Only located in `<appDataDir>\brain\<id>\scratch\` | **Keep outside repo** (none pollute workspace) | LOW |
| `audit/01..07_*.md`, `STATIC_AUDIT_REPORT.md`, `proof/PROOF_REPORT.md`, `CHANGES_AND_UPGRADE_TASK_SHEET.md`, `CloudBalance_Team_Workflow.html`, `local draft one/`, `01_Documentation_And_Reports/` | Historical reports / viva packages | **Keep `audit/` & `proof/`** (explicitly tracked or move old drafts to `archive/` if desired after approval) | LOW |

---

## 3. Architecture Layers & Oversized Modules

- **Layer separation check:**
  - **Worker -> Controller:** Clean (`worker/executor.py` and `worker/agent.py` have **zero** imports of `backend`, `app`, `ortools`, `motor`, or `redis`).
  - **Controller -> Worker (`CROSS-LAYER COUPLING`):** [tasks.py:L463-L466](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/api/tasks.py#L463-L466) directly imports `_calculate_cgpa` and `_run_heavy_hashing_loop` from `worker.executor` for the virtual/in-process fallback path. When Controller deploys in a separate VM/container without `worker/`, this raises `ModuleNotFoundError` if `seed_demo_workers=true` or failover triggers virtual execution!
  - **Tests -> Layers:** Integration tests import `worker.executor`, `worker.agent`, `traffic.*`, `tools.load_client` directly (expected for end-to-end tests in single-repo workspace).
  - **Route handler bloat / `>450L` modules (Proposal Only — Do NOT split without approval):**
    - `backend/app/api/tasks.py` (`706L`): mixes Pydantic schemas, rate-limiting/payload size checks, mode resolution, inline MILP lock/dispatch, HTTP worker transport + failover, virtual fallback, and CSV/stats recording.
    - `backend/app/api/admin.py` (`578L`): mixes `ActiveTestManager` state machine & background lifecycle tasks with FastAPI admin/auth/stats/CSV endpoints.
    - `worker/executor.py` (`530L`): mixes FastAPI app factory, bounded semaphore queue, compute kernels, and inline HTTP telemetry pushing.
    - `frontend/src/pages/OpsCenterPage.tsx` (`875L`), `PublicTasksPage.tsx` (`632L`), `BenchmarkSection.tsx` (`581L`), `ClientLoadPage.tsx` (`479L`): monolith page components combining charts, tables, forms, and API polling.
    - `backend/tests/test_edge_cases_senior_audit.py` (`967L`), `backend/tests/test_admin_and_contracts.py` (`712L`), `frontend/src/__tests__/App.test.tsx` (`575L`), `benchmark/run_benchmark.py` (`451L`).

---

## 4. Dead Code & Unused Items

1. **Unused runtime scheduler (`backend/app/schedulers/round_robin.py` `93L`):** Runtime `round_robin` mode uses atomic `redis_client.incr("rr_counter")` in `tasks.py:298-300`; `RoundRobinScheduler` is only imported by offline `benchmark.py` and `benchmark/run_benchmark.py` and unit-tested in `test_schedulers.py`.
2. **Broken offline script (`benchmark/run_benchmark.py:46, 134`):** Imports deleted `LeastConnectionsScheduler` (`ModuleNotFoundError` on `make bench` and `.github/workflows/ci.yml:45`).
3. **Leftover `paused` flag (`7` files, zero UI button):**
   - `backend/app/services/scheduler_state.py:16,33,47-48,61-62`
   - `backend/app/api/control.py:72,78-79,99`
   - `backend/app/services/broadcaster.py:78`
   - `backend/app/models/schemas.py:323,340`
   - `frontend/src/lib/types.ts:69`
   - `frontend/src/__tests__/App.test.tsx:68`
   - `backend/tests/test_controller_api_and_services.py:101`
4. **Dead / uncalled routes:** `GET /api/v1/health`, `WS /api/v1/ws`, `GET /api/v1/mongo` (overlaps `/api/v1/telemetry/mongo`), `POST /api/v1/control/traffic`, `POST /api/v1/control/workers/{id}/kill|revive`.
5. **Unused `Settings` fields (`backend/app/core/config.py`):**
   - Leftover micro-batcher fields: `batch_window_ms`, `batch_max_size` (`UNUSED` in `backend/app/`).
   - Ignored/dead config fields: `rate_limit_per_sec`, `max_queue_depth`, `dispatch_timeout_sec` (`tasks.py` hardcodes `httpx.AsyncClient(timeout=15.0)`), `dispatch_max_retries`, `environment`, `controller_url`/`controller_port` (read via `os.getenv` in `run_cluster.py`, not `Settings`), `data_dir` (note `logger.py` reads `os.getenv("CB_DATA_DIR")` directly instead of `get_settings().data_dir`).

---

## 5. Config & Environment Discipline

- **Env var parity mismatch across `.env`, `.env.example`, `README.md`, `Settings`, and `worker/`:**
  - `.env` defines only `8` keys (`ADMIN_TOKEN`, `CB_ALLOWED_ORIGINS`, `CB_DATA_DIR`, `CB_LOCAL_MODE`, `CB_MAX_PAYLOAD_BYTES`, `CB_RATE_LIMIT_PER_MIN`, `WORKER_SECRET`, `WORKER_URLS`).
  - `.env.example` defines `33` keys, **missing** `13` worker variables read directly via `os.getenv` in `worker/executor.py` & `worker/agent.py`: `WORKER_ID`, `WORKER_IP`, `WORKER_PORT`, `WORKER_TOTAL_MEM_MB`, `WORKER_BASE_CPU_PCT`, `WORKER_BASE_MEM_MB`, `WORKER_TIME_SCALE`, `WORKER_MAX_PHYSICAL_DIM`, `WORKER_CONCURRENCY_LIMIT`, `WORKER_QUEUE_CAPACITY`, `WORKER_TASK_TIMEOUT_SEC`, `WORKER_ENABLE_AGENT`, `WORKER_TELEMETRY_INTERVAL`, `HEAVY_TASK_ITERATIONS` (`worker/executor.py:29`).
  - `.env.example` still lists unused GCP vars (`REDIS_PASSWORD`, `GCP_*`, `ALLOWED_CIDR`) and unused `CB_API_KEY`, `CB_REQUIRE_API_KEY` context differs on `/tasks` vs `/api/v1/tasks`.
  - `README.md` mentions only `11` env vars (`ADMIN_TOKEN`, `WORKER_SECRET`, `WORKER_URLS`, `CB_ALLOWED_ORIGINS`, `CB_LOCAL_MODE`, `CB_RATE_LIMIT_PER_MIN`, `CB_REDIS_URL`, `ALLOWED_CIDR`, `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ZONE`).
- **Hardcoded hosts / ports / worker IDs / URLs outside `Settings` defaults:**
  - `backend/app/api/tasks.py:174` (`return "http://127.0.0.1:8001/execute"` fallback) & `489` (`timeout=15.0`).
  - `backend/app/api/benchmark.py:76-140` (`"10.128.0.10"`, `"worker-1..3"`).
  - `backend/app/core/logger.py:29` (`os.getenv("CB_DATA_DIR") or os.getenv("DATA_DIR")`, bypasses `Settings`), `L384-396` (`worker-1..3` columns).
  - `backend/app/core/live_stats.py:10,21`, `test_hooks.py:23`, `admin.py:323` (hardcoded `("worker-1", "worker-2", "worker-3")`).
  - `backend/app/core/mongo_client.py:123` (`mongodb://localhost:27017` default), `redis_client.py:135` (`redis://localhost:6379/0` default).
  - `worker/agent.py:98, 164-169` & `worker/executor.py:70-71, 237` (`http://localhost:8000` vs `http://127.0.0.1:8000`, `worker-1`, `127.0.0.1`).
  - `worker/entrypoint.sh:6-9` (`http://controller:8000`, `worker-1`).
  - `scripts/verify_worker_b1.py:15` (`worker_url = "http://127.0.0.1:8001"` hardcoded without env override).
  - `traffic/cli.py:24` (`--target-url` default `"http://localhost:8000"` without `CB_BASE_URL` env fallback).
  - `frontend/src/pages/OpsCenterPage.tsx:56, 340-394` (`WORKER_NAMES = ["worker-1", "worker-2", "worker-3"]` hardcoded).
  - `frontend/vite.config.ts`: proxy target (`http://localhost:8000` dev server only).
  - **No hardcoded secrets** in active `backend/`, `worker/`, `frontend/src/` (except inactive `Settings.api_key` default `"cb-dev-api-key-2026"` & root `docker-compose.yml` fallback `"cb-redis-local-pass"` / `"cb-dev-api-key-2026"`).

---

## 6. Naming & Consistency Discrepancies

| Area | Discrepancy | Evidence |
|---|---|---|
| **Scheduler name** | Test `mode="milp"` & `/test/status` vs `scheduler_used="ortools_milp"` & `Settings.default_scheduler="ortools_milp"` | `admin.py:77`, `tasks.py:334`, `config.py:220` |
| **Client IDs** | Browser `/client` uses `client-xxxx`, `tools/load_client.py` uses `laptop-1`, simulator uses `sim-1`, `/` uses `public-web-client` | `ClientLoadPage.tsx`, `load_client.py:126`, `simulator.py:130`, `PublicTasksPage.tsx:94` |
| **Worker fallback URL** | `worker/agent.py` defaults to `http://localhost:8000`, `worker/executor.py` to `http://127.0.0.1:8000`, `entrypoint.sh` to `http://controller:8000` | `agent.py:169`, `executor.py:237`, `entrypoint.sh:9` |
| **Task API auth** | `POST /api/v1/tasks` requires `verify_api_key` while `POST /tasks` does not | `tasks.py:684-706` |
| **Field naming** | Worker JSON `execution_ms` -> CSV `exec_ms` -> schema `duration_sec` | `executor.py:512`, `logger.py:52` |
| **Worker count in GCP** | Local cluster runs **3 workers** (`worker-1..3`), while `infra/gcp/provision.sh:105` provisions only **2 workers** (`for IDX in 1 2`) | `provision.sh:105`, `run_cluster.py:19-23` |

---

## 7. Dependencies & Runtime Versions

- **Runtime versions:**
  - `backend/pyproject.toml:10`, `.github/workflows/ci.yml:20`, `backend/Dockerfile:1`, `worker/Dockerfile:1`: `Python >= 3.11` (CI/Docker `3.11`; local environment tested on **`Python 3.14.7`**).
  - `.github/workflows/ci.yml:60`, `frontend/Dockerfile:1`: `Node 20` (local tested on **`Node v24.11.1`**). README does not state explicit Node or Python version prerequisites!
- **Dependency splitting & pinning:**
  - `frontend/package.json` uses caret ranges (`^`) backed by `frontend/package-lock.json` (`4578L` exact lockfile).
  - `backend/pyproject.toml` uses unpinned `>=` lower bounds (`fastapi>=0.110.0`, `ortools>=9.9.0`, etc.); no `constraints.txt` / lockfile. Contains **`ortools>=9.9.0`**, `redis`, `motor` (controller-only). Missing optional `matplotlib` (used by `benchmark/run_benchmark.py`, installed separately in `.github/workflows/ci.yml:26`).
  - `worker/requirements.txt` (`8L`): Already cleanly excludes `ortools`, `motor`, `redis` (`fastapi`, `uvicorn[standard]`, `pydantic`, `numpy`, `psutil`, `httpx`, `structlog`), though all versions are unpinned `>=`.
  - Root `requirements*.txt` files are missing (only `backend/pyproject.toml`, `worker/requirements.txt`, `traffic/pyproject.toml` exist). Separating `deploy/requirements-controller.txt` + `deploy/requirements-worker.txt` (or adding pinned constraints) makes single-role GCP VM installs deterministic.

---

## 8. Documentation Accuracy (`README.md`)

Every stale/inaccurate claim verified in [README.md](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/README.md):
1. **Architecture (`L3`, `L140`, `L157`, `L294`):** Claims active `200ms` micro-batching, `Batcher`, `Dispatcher`, and `LeastConn` — all removed from `/tasks` dispatch path (`tasks.py` runs direct inline MILP or atomic RR `INCR`).
2. **Structure Tree (`L14–35`):** Documents `Local-Version/` + empty `Public-Version/` instead of root `backend/`, `frontend/`, `worker/`, `tools/`, `scripts/`, `tests/`.
3. **Routes & `/client` (`L61, L132, L197-198, L286, L289`):** `L61` claims `legacy /client redirects to /`, whereas `/client` now serves `ClientLoadPage` (`0.5–10 req/s` Poisson load generator). `L197` & `L286` list `/` as Ops Dashboard (`Ops` is actually at `/ops` behind `ADMIN_TOKEN`). `L293` describes old `/client` single-task button instead of `Start Poisson`/`Stop`.
4. **Profile Table (`L172-177`):** Lists stale `2400 / 4.0s`, `1024 MB / 4500 / 5.0s` instead of actual [profiles.py:L37-L86](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/core/profiles.py#L37-L86) (`1500 / 3.0s`, `384 MB / 2200 / 3.0s`) and omits `LIGHT` and `HEAVY`.
5. **Startup & Secrets (`L192-196, L236`):** `docker compose up` and `infra/gcp/provision.sh` instructions fail cleanly unless updated to supply required `ADMIN_TOKEN` and `WORKER_SECRET`.
6. **`cb-traffic` vs `load_client.py` (`L154, L249`):** Architecture diagram shows `POST /api/v1/tasks`, while benchmark contract relies on `tools/load_client.py` and `/client` hitting `POST /tasks`.

---

## 9. GCP Deploy-Readiness Gap List (1 Controller + 3 Private Worker VMs)

| Area | Current State | GCP Gap for `1 Controller + 3 Workers` |
|---|---|---|
| **Worker VM Count** | `infra/gcp/provision.sh:105` creates **2** workers | Must provision **3** internal-only VMs (`worker-1..3`, `--no-address`, internal VPC IPs) |
| **Required Secrets** | Controller requires `ADMIN_TOKEN` & `WORKER_SECRET` (`config.py:89-96`) | `provision.sh`, `startup-controller.sh`, `startup-worker.sh`, `docker-compose.yml` omit `ADMIN_TOKEN` & `WORKER_SECRET` (startup crash / `401` telemetry) |
| **Bind & `WORKER_URLS`** | `systemd` binds `0.0.0.0:8000` (controller) & `0.0.0.0:8001` (worker) | Set `WORKER_URLS=http://10.128.0.11:8001,http://10.128.0.12:8001,http://10.128.0.13:8001` and `CONTROLLER_URL=http://10.128.0.10:8000`; tighten controller firewall vs public `/client` |
| **Nginx Reverse Proxy** | `infra/nginx/nginx.conf` proxies only `/api/`, `/health`, `/ready`, `/ws` to `http://controller:8000` | **Critical:** `/tasks`, `/admin/`, `/test/`, `/healthz` fall through to React `index.html` (`405`/`404`); missing `client_max_body_size 64k` matching `MAX_PAYLOAD_BYTES`; needs `127.0.0.1:8000` for VM systemd + `X-Forwarded-Proto` |
| **`CB_LOCAL_MODE` / Uvicorn Workers** | `systemd` passes `--workers 1`, `backend/Dockerfile` runs `uvicorn` | Must remain **`--workers 1`** if `CB_LOCAL_MODE=true` (in-memory Redis/locks/`_active_tasks`); even with `REDIS_URL`, `ActiveTestManager` & `InFlightTracker` & CSV queue are process-local! |
| **Cross-Layer Import** | `tasks.py:463,466` imports `worker.executor` | Harmless if only HTTP workers run (`seed_demo_workers=false`), crashes if `virtual` fallback triggers on a controller-only VM without `worker/` |
| **Proxy Headers & CORS** | `uvicorn` lacks `--proxy-headers`, `ALLOWED_ORIGINS` defaults `["*"]` | Add `--proxy-headers --forwarded-allow-ips='127.0.0.1'`; set `CB_ALLOWED_ORIGINS` strictly to public domain/IP |
| **`DATA_DIR`, Permissions & Archiving** | `CB_DATA_DIR=data` relative to `WorkingDirectory`, zero log rotation, CSV grows unbounded | Set explicit writable path (`/var/lib/cloudbalance/data` owned by `ubuntu`), configure logrotate/journald limits; note `/admin/stats/reset` archives CSVs cleanly to `archive/` |
| **Healthchecks & Graceful Shutdown** | `/healthz` (`Health`), `/ready` (active workers count); lifespan flushes `csv_logger` | Nginx/LB can probe `/healthz` cleanly; `systemd` needs `TimeoutStopSec=25` so draining/CSV flush finishes cleanly |
| **Firewall Rules** | `provision.sh` restricts 80/443/8000 to single `ALLOWED_CIDR` | For multi-laptop `/client` mobile demos: allow `80/443` publicly (or hotspot CIDR) while blocking direct `:8000` externally (or allow `:8000` if no Nginx), allow `:8001` **ONLY** from controller's internal IP (`10.128.0.10/32`), restrict `:22` SSH (`--tunnel-through-iap` or operator CIDR) |
| **Time Sync & Startup Order** | Client `sent_at` uses client clock; workers post telemetry to controller | Enable `systemd-timesyncd`/`chrony` on VMs; start controller + Redis before (or let worker `agent.py` retry telemetry); `systemd` `Restart=always` handles worker-before-controller startup |
| **Worker Down at Startup** | `tasks.py:306-320` seeds offline defaults only if `seed_demo_workers=true` (`tasks.py:553` logs `unavailable` if `seed_demo_workers=false`) | Controller **starts cleanly** with `0` workers (`/ready` returns `active_workers: 0`), `/ops` reflects offline until worker heartbeats arrive (`worker_ttl_seconds=10s`), tasks fail cleanly with `unavailable` unless virtual fallback disabled |

---

## 10. Numbered Cleanup Plan (Phase 2 — Awaiting Approval)

| Step | Action & Exact Files Touched | Risk | Rollback |
|---:|---|---|---|
| **2a** | Update root [`.gitignore`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/.gitignore) to track active source (`backend/`, `frontend/src/`, `worker/`, `traffic/`, `benchmark/`, `infra/`, `scripts/`, `tests/`, `tools/`, `deploy/`, templates); move stale zips (`CloudBalance.zip`, `pre-client-page.zip`), root logs (`cluster_*.log`, `run_cluster.log`), `.coverage`, `backend/.coverage`, and `backend/.env` to `archive/` | LOW | `git checkout pre-structure-pass -- .gitignore` & restore from `archive/` / external zip |
| **2b** | *(Pending explicit approval on `Local-Version/`)* Archive/move `Local-Version/` and `Public-Version/` out of active tree (e.g. `archive/legacy/`) so ONE source of truth remains and `"cb-admin-secret-2026"` is removed from tracked HEAD; **resolve duplicate `tests/test_shared_contract_suite.py`**: move duplicate root copy to `archive/` (or consolidate into `backend/tests/test_shared_contract_suite.py` while keeping `pytest >= 71` by retaining/converting distinct contract coverage in `backend/tests/` before removing duplicate) | MED | Restore via `git checkout pre-structure-pass` / `C:\Users\sumed\cloudbalance-snapshots\pre-structure-pass.zip` |
| **2c** | Consolidate hardcoded config into `Settings` / env: route `logger.py` `DATA_DIR` through `get_settings()`, respect `Settings.dispatch_timeout_sec` in `tasks.py`, add env-var URL override to `scripts/verify_worker_b1.py` & `traffic/cli.py`, remove hardcoded `"cb-dev-api-key-2026"` / password fallbacks from `docker-compose.yml` & `config.py` *(keep local dev smooth cleanly without breaking tests!)* | MED | Revert single commit / restore files from snapshot |
| **2d** | Fix naming/doc discrepancies: document exact worker env vars in `.env.example`, fix `benchmark/run_benchmark.py` broken `LeastConnectionsScheduler` import (so `make bench` & CI run cleanly), update `README.md` for `/`, `/client`, `/ops`, `/benchmark`, actual `profiles.py`, and zero micro-batcher | LOW | `git checkout` / restore from snapshot |
| **2e** | *(Only if explicitly approved)* Remove leftover dead `paused` flag across `scheduler_state.py`, `control.py`, `broadcaster.py`, `schemas.py`, `types.ts`, `App.test.tsx`, `test_controller_api_and_services.py`, and remove dead `batch_window_ms` / `batch_max_size` from `Settings` | MED | Revert single step if any baseline fails |
| **2f** | Document exact Python `>=3.11` & Node `>=20` versions, split/pin `deploy/requirements-controller.txt` and `deploy/requirements-worker.txt` (worker free of `ortools`/`motor`/`redis`) without breaking editable installs | LOW | Restore `requirements.txt` / `pyproject.toml` |

### Phase 3 Plan Addendum — GCP VM Python Version Requirement (Verified Post-Step-2f)
- **Target Range:** `Python >= 3.11` (`backend/pyproject.toml`, `backend/Dockerfile`, `worker/Dockerfile`, `numpy==2.2.6; python_version < "3.12"` and `numpy==2.5.3; python_version >= "3.12"`).
- **Local Verification Status:** Pinned controller (`backend/requirements.txt`) and worker-only (`worker/requirements.txt`) requirements were verified end-to-end on **`Python 3.14.7`** only (`C:\Python314\python.exe`). **Python `3.11` and `3.12` are NOT verified locally** (`3.11`/`3.12` interpreters are not installed on this workstation).
- **Phase 3 / Phase 4 Gate:** Explicitly document the VM Python version in Phase 3 (`deploy/gcp/README.md`) and verify `pip install -r backend/requirements.txt` / `pip install -r worker/requirements.txt` directly on the target GCP VM image (`Ubuntu 22.04` / `24.04`) during Phase 3/4.

**Stopping here after Phase 1 report.** Awaiting your approval before executing Phase 2 (specifically confirming: `(1)` moving/archiving `Local-Version/` & `Public-Version/`, `(2)` handling duplicate `tests/test_shared_contract_suite.py`, and `(3)` removing leftover `paused` + `batch_window_ms`/`batch_max_size`).
