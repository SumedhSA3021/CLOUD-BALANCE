# CloudBalance Final Structure, Architecture & GCP Readiness Report (Phase 4)

**Status:** Structure cleanup (Phase 2), GCP packaging (Phase 3), and pre-push local verification (Phase 4) complete.  
**Constraints Respected:** Zero commits, zero pushes, zero `gcloud` commands executed, and zero unapproved application code modifications.  
**Pre-Pass Snapshot Backup:** External zip preserved outside repository at `C:\Users\sumed\cloudbalance-snapshots\pre-structure-pass.zip`.

---

## 1. Before / After Repository Tree

### Before (`HEAD` `pre-structure-pass` — `124` tracked files + untracked overlapping root copies)
```text
CLOUD-BALANCE/ (pre-pass state)
├── Local-Version/              (112 tracked legacy mirror files + uncommitted leftovers)
├── Public-Version/             (1 empty .gitkeep placeholder)
├── backend/                    (IGNORED in .gitignore; shadowed by backend/.env & Local-Version/)
├── frontend/                   (IGNORED in .gitignore; tracked only inside Local-Version/)
├── worker/                     (IGNORED in .gitignore)
├── infra/                      (IGNORED in .gitignore; only 2 workers, missing tokens/Nginx routes)
├── traffic/                    (IGNORED in .gitignore)
├── tests/                      (2 files incl. duplicate tests/test_shared_contract_suite.py)
├── scripts/                    (3 tracked files + 3 untracked)
├── tools/load_client.py
├── .gitignore                  (ignored active root packages while tracking Local-Version/)
├── pytest.ini                  (ran both backend/tests & duplicate root tests/)
└── README.md                   (stale Local-Version/ & Public-Version/ references)
```

### After (Unified Single Root Source of Truth)
```text
CLOUD-BALANCE/
├── backend/                    (Controller, OR-Tools MILP/RR, requirements.txt, pyproject.toml [+dev,+bench], tests/ [15 modules, 86 tests])
├── frontend/                   (React 18 + TS + Tailwind SPA, Vitest [13 tests], package-lock.json; dist/ & node_modules/ ignored)
├── worker/                     (Executor + psutil agent, entrypoint.sh, Dockerfile, slim requirements.txt)
├── deploy/                     (Production GCP VM configs: controller/worker env templates, nginx, systemd, gcp/README.md)
├── infra/                      (GCP provision/startup/teardown scripts, Docker nginx, systemd copies)
├── scripts/                    (run_local.{ps1,sh}, load_client.py, preflight.py, smoke_test.py, final_acceptance.py, verify_*.py)
├── traffic/                    (cb-traffic CLI package with synchronized httpx/pydantic pins)
├── benchmark/                  (Offline 2-scheduler replay suite + results/ plots)
├── docs/                       (Consolidated docs: audit/, proof/, project-reports/, drafts/)
├── tests/                      (Root test package init; active pytest suite in backend/tests/)
├── .env.example                (Local env template; .env gitignored)
├── .github/workflows/ci.yml    (Updated CI using ./backend[dev,bench] + ruff over scripts/)
├── conftest.py                 (Single root pytest configuration)
├── docker-compose.yml          (Secondary container stack; images not built/tested)
├── Makefile                    (Developer test/lint/bench automation targets)
├── pyrightconfig.json          (Excludes docs/ and archive/)
├── pytest.ini                  (testpaths = backend/tests)
└── README.md                   (Updated layout, dependency table, local/GCP setup & caveats)
```

---

## 2. Moved, Removed & Merged Items Inventory

| Category | Items | Action & Rationale |
|---|---|---|
| **Removed Legacy Mirrors & Old Docs Layout** | `Local-Version/`, `Public-Version/.gitkeep`, `tests/test_shared_contract_suite.py`; moved `audit/`, `proof/`, `01_Documentation_And_Reports/`, `local draft one/`, root workflow docs into `docs/`; moved `tools/load_client.py` -> `scripts/load_client.py` | Consolidated scattered docs under `docs/{audit,proof,project-reports,drafts}/` and runnable utilities under `scripts/` without losing any files; synchronized dependency pins in [backend/tests/test_repo_structure_and_deps.py](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/tests/test_repo_structure_and_deps.py). |
| **Cleaned Stale Root Artifacts** | `backend/.env`, stale root `.coverage`, `backend/.coverage`, old `.log`/`.zip` archives | Removed/gitignored stale artifacts so root `.env` is the sole local override (`*.db`, `*.sqlite*`, `/data/`, `frontend/dist/`, `.env`, `deploy/*.env` ignored in [.gitignore](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/.gitignore)). |
| **Consolidated Deployment Templates** | Added `deploy/` (`controller.env.example`, `worker.env.example`, `nginx/nginx.conf`, `systemd/*.service`, `gcp/README.md`) & updated `infra/gcp/*.sh`, `infra/nginx/nginx.conf`, `infra/systemd/*.service` | Split GCP VM primary configs (`deploy/`) from secondary Docker Compose configs (`infra/nginx/nginx.conf`, `docker-compose.yml`); added `backend/requirements.txt` split from [worker/requirements.txt](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/worker/requirements.txt). |
| **Verification & Preflight Additions** | [scripts/preflight.py](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/scripts/preflight.py), [backend/tests/test_preflight.py](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/tests/test_preflight.py), [scripts/final_acceptance.py](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/scripts/final_acceptance.py) | Enforces `ADMIN_TOKEN`/`WORKER_SECRET` >= 32 chars, `CB_SEED_DEMO_WORKERS=false`, 3 valid worker endpoints, port/data-dir readiness, and automated `A–L` acceptance (`B1` integrity + `B2` failure/503 observation). |

---

## 3. Fresh-Clone Simulation & Grep Proof Summary

- **Fresh-Clone Simulation (`143` non-ignored repo files copied to isolated temp folder):**
  - Confirmed absent before setup: `.env`, `frontend/dist/`, `frontend/node_modules/`, `data/`.
  - Generated `.env` from [deploy/controller.env.example](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/deploy/controller.env.example) substituting fresh `32+` char test secrets, localhost worker/controller endpoints (`127.0.0.1:8000` / `:8001–:8003`), and Windows-local `CB_DATA_DIR="data"` (in place of Linux `/var/lib/cloudbalance/data`).
  - Clean venv installs (`pip install -r worker/requirements.txt` -> `pip check` + `import worker.executor, worker.agent`; `pip install -r backend/requirements.txt` -> `pip check` + `import app.main, dotenv`), `frontend` `npm ci && npm run build`, `scripts/run_local.ps1`, `scripts/preflight.py` (`PASS=4 SKIP=1 FAIL=0`), and `scripts/smoke_test.py` (`ALL SMOKE TEST CHECKS PASSED!`) **all passed (`exit 0`) with zero missing files in the clone**. *(Note: controller VM deployment substitutes real private VPC IPs/secrets into `deploy/controller.env.example`, and local test/lint suites additionally use `./backend[dev]`.)*
- **Grep Proof:**
  - **Duplicate config/env/conftest check:** Exactly one root [conftest.py](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/conftest.py), one [backend/app/core/config.py](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/core/config.py), one local `.env.example`, one local `.env` (gitignored), plus `deploy/controller.env.example` and `deploy/worker.env.example`.
  - **Secret literal scan:** Zero hardcoded secrets in runtime/deploy/infra files (the only 3 string hits in the repository are `KNOWN_LEGACY_SECRETS` inside [scripts/final_acceptance.py:49-53](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/scripts/final_acceptance.py#L49-L53) used to fail rotated-token checks against git history).
  - **Host/port literal scan:** Zero non-test `localhost`/`127.0.0.1`/port literals in `frontend/src/` or `frontend/dist/`, and zero hardcoded runtime IPs/ports in `backend/app/` outside centralized defaults in `config.py` (remaining runtime matches are strictly worker CLI defaults in `worker/executor.py`, CLI defaults in `scripts/load_client.py` & `traffic/cli.py`, Docker Compose internal hostnames, Nginx upstream `127.0.0.1:8000` / `controller:8000`, and parameterized shell/systemd vars).

---

## 4. Remaining Known Gaps

1. **`ClientLoadPage` does not auto-stop when a test ends:** [ClientLoadPage.tsx:119-139](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/pages/ClientLoadPage.tsx#L119-L139) polls `/test/status` solely to render the status banner; clicking **Stop** ([L388](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/pages/ClientLoadPage.tsx#L388)) freezes `elapsedMs` & `achievedRate`, so until the user clicks Stop manually after the controller transitions to `draining`/`idle`, `elapsedMs` (`L213-216`) and `sent` (`L162`, receiving `409`s at `L174-175`) continue advancing.
2. **Browser background-tab throttling limits rate to `~1 req/s`:** [ClientLoadPage.tsx:218-228](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/pages/ClientLoadPage.tsx#L218-L228) schedules each send via sequential `window.setTimeout(..., gapMs)` without target-clock catch-up or a Web Worker timer. Browsers clamp inactive/backgrounded tabs to `>= 1000 ms`, causing declared `3/s` tabs behind `/ops` or other windows to send only `~30` tasks in `30 s`.
3. **`scripts/preflight.py` needs `CB_SEED_DEMO_WORKERS=false`:** Deliberately enforced in Check 1; `deploy/controller.env.example` sets `"false"`, whereas local `.env` omits it so bare local `python scripts/preflight.py` must export `CB_SEED_DEMO_WORKERS=false` (or use `--env-file`).
4. **Bounded worker queue saturation under `round_robin` bursts:** Workers enforce `WORKER_QUEUE_CAPACITY=4` (`worker/executor.py`); blind `round_robin` bursts can occasionally trigger `status="rejected_503"` (`test-204fbe93` logged `10`, while `0/5` occurred across clean alternating `5x` RR pairs and `0` across all MILP runs), captured as `B2` `OBSERVATION` in `final_acceptance.py`.
5. **Controller virtual-fallback import:** [backend/app/api/tasks.py:468,471](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/api/tasks.py#L468-L471) still imports `worker.executor` only if `CB_SEED_DEMO_WORKERS=true` / `virtual` worker execution runs (inert in GCP when `CB_SEED_DEMO_WORKERS="false"`).
6. **Plain HTTP transport warning:** Plain HTTP (`:80`) sends `ADMIN_TOKEN` / `/ws?token=` unencrypted unless TLS (`HTTPS` / Cloudflare Tunnel) or Nginx `ALLOWED_ADMIN_CIDR` IP allowlisting is configured per [deploy/gcp/README.md](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/deploy/gcp/README.md).

---

## 5. GCP Go / No-Go Checklist

| Gate | Requirement | Go Criterion |
|---|---|---|
| **1. Auth & Secrets** | Fresh >= 32-char `ADMIN_TOKEN` & `WORKER_SECRET` exported before `provision.sh`; never committed | Controller `.env` & Worker `.env` written with `chmod 600`; zero defaults or secret echoes |
| **2. IP & Firewall Isolation** | Separate `<CONTROLLER_INTERNAL_IP>` vs `<CONTROLLER_STATIC_EXTERNAL_IP>`; `3` workers `--no-address` | `:80,:443` public (`NOT 8000`); `:8000` worker `/32`s -> controller only; `:8001` controller `/32` -> workers only; `:22` `<ADMIN_SSH_CIDR>` only |
| **3. VM Runtime & Deps** | Python `>= 3.11` (`3.11/3.12`) `pip install` & `pip check` on all 4 VMs; single uvicorn `--workers 1` (`CB_LOCAL_MODE="true"`, `CB_SEED_DEMO_WORKERS="false"`) | `pip check` exits `0` on Controller & `worker-1..3` (first live validation of 3.11/3.12 pins!) |
| **4. Controller-VM Pre-Share Test** | Run `preflight.py --env-file /etc/cloudbalance/controller.env`, worker `:8001/healthz` curls, Nginx `nginx -t` & `smoke_test.py` from Controller VM | All 5 preflight checks pass/skip (`FAIL=0`), `/ready` shows `active_workers=3`, `smoke_test.py` exits `0` |
| **5. Ops Privacy & TLS** | Restrict `/ops`, `/benchmark`, `/admin/`, `/api/v1/control`, `/api/v1/telemetry`, `/api/v1/benchmark` before sharing public `/client` | Either `ALLOWED_ADMIN_CIDR` enabled in Nginx or HTTPS/Cloudflare Tunnel active |
| **6. Post-Review Teardown** | Run `bash infra/gcp/teardown.sh` immediately after demo | All 4 VMs, static IP, NAT, router, firewalls, subnet, VPC deleted & remaining resources list empty |

---

## 6. Honest NOT-Verified List (Local Windows Host Scope)

The following items were **not** executed or verified in this environment and require validation on target GCP VMs / external clients:
- **Internal-IP VPC routing** between Controller VM and private Worker VMs (`10.x` VPC network traffic)
- **GCP firewall rules** (`FW_CONTROLLER_HTTP`, `FW_CONTROLLER_SSH`, `FW_WORKERS_TO_CONTROLLER`, `FW_CONTROLLER_TO_WORKERS`)
- **Reserved Static External IP** assignment and external/internal IP separation on live GCE instances
- **`nginx -t`** and live Nginx reverse proxy / WebSocket upgrade / `ALLOWED_ADMIN_CIDR` enforcement (`nginx` not installed locally)
- **`systemd`** unit validation (`systemd-analyze verify` unavailable locally) and Linux VM service boot/restart behavior
- **Python `3.11 / 3.12`** installation & dependency resolution for `backend/requirements.txt` and `worker/requirements.txt` (verified locally ONLY on **Python `3.14.7`**)
- **Docker builds & Compose runtime** (`docker-compose.yml`, `*/Dockerfile`, `worker/entrypoint.sh` — **secondary, images not built or tested**; only static `docker compose config -q` checked)
- **Real external Redis & MongoDB path (`CB_LOCAL_MODE=false`)** end-to-end execution
- **HTTP traffic from mobile networks** (`4G/5G` hotspot or remote multi-laptop clients over public internet)
- **`gcloud` provisioning & teardown scripts (`infra/gcp/*.sh`)** — checked with `bash -n` and static grep only, **never executed against GCP**
