# CloudBalance GCP Compute Engine Deployment Runbook

Deploy CloudBalance cleanly onto Google Cloud Compute Engine (`1` Controller VM behind Nginx + `3` private `--no-address` Worker VMs) using `infra/gcp/provision.sh` and systemd.

---

## Verification & Support Status (Read Before Deploying)

| Component / Path | Status | Details |
|---|---|---|
| **Primary GCP Path (`deploy/` + `infra/gcp/` + systemd + Nginx)** | **Statically verified; `gcloud` scripts never executed** | Scripts checked with `bash -n`, CLI flags checked against `uvicorn`/`worker.agent`, Nginx routes matched statically against FastAPI routes. Not yet executed against live GCP VMs. |
| **Runtime Mode (`CB_LOCAL_MODE="true"`, single `--workers 1` uvicorn)** | **Tested configuration** | Keeps `rr_counter`, `ActiveTestManager`, and in-flight reservations consistent in one Controller process without external Redis/Mongo daemons. |
| **Python Versions (`backend/requirements.txt`, `worker/requirements.txt`)** | **Pins verified ONLY on Python `3.14` (`3.14.7`)** | **Python `3.11 / 3.12` pins are NOT verified locally.** Startup scripts check `python3 --version` and run `pip install` + `pip check` on the VM during provisioning. |
| **External Redis / MongoDB (`CB_LOCAL_MODE="false"`)** | **UNVERIFIED end-to-end** | Optional and unsupported unless explicitly configured and tested separately on the Controller VM. |
| **Docker Compose Stack (`docker-compose.yml`, `*/Dockerfile`)** | **secondary, images not built or tested** | Kept for container workflows only (`infra/nginx/nginx.conf`); use native systemd + Nginx for GCP VMs. |

---

## Topology & IP Separation

```text
Internet Clients (/client, /, /tasks, /test/status, /healthz)
   │
   ▼  HTTP :80 / HTTPS :443  (FW_CONTROLLER_HTTP — TCP 8000 is NEVER opened externally)
┌──────────────────────────────────────────────────────────────────────┐
│ Controller VM (cloudbalance-controller, e2-standard-2)               │
│   Public IP : <CONTROLLER_STATIC_EXTERNAL_IP>  (browser/client URL)  │
│   VPC IP    : <CONTROLLER_INTERNAL_IP>         (worker heartbeats)   │
│   Nginx (:80) -> uvicorn 127.0.0.1:8000 (--workers 1)                │
│   Controller Dispatch -> http://<WORKER_1..3_INTERNAL_IP>:8001       │
└───────────────▲───────────────────────────────────────┬──────────────┘
                │ POST /api/v1/telemetry (1.5s)         │ POST /execute
                │ FW_WORKERS_TO_CONTROLLER (:8000)      │ FW_CONTROLLER_TO_WORKERS (:8001)
┌───────────────┴───────────────────────────────────────▼──────────────┐
│ Private Worker VMs (--no-address, cloudbalance-worker-1..3, tag cb-worker)
│   - No public IP; outbound apt/pip uses Cloud Router + Cloud NAT      │
│   - cloudbalance-worker-executor.service (:8001, --workers 1)        │
│   - cloudbalance-worker-agent.service (--interval 1.5)               │
└──────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> Strictly separate `<CONTROLLER_INTERNAL_IP>` from `<CONTROLLER_STATIC_EXTERNAL_IP>`. Never reuse one value for both:
> - `CONTROLLER_URL` (`worker.env`), `FW_CONTROLLER_TO_WORKERS`, and `FW_WORKERS_TO_CONTROLLER` **always** use VPC internal IPs.
> - Browser URLs (`/client`, `/ops`), `CB_ALLOWED_ORIGINS`, and client scripts **always** use `<CONTROLLER_STATIC_EXTERNAL_IP>` (or your HTTPS domain).

---

## 1. Prerequisites

Before running `infra/gcp/provision.sh`:

1. Install and authenticate the Google Cloud CLI:
   ```bash
   gcloud auth login
   gcloud config set project "<GCP_PROJECT_ID>"
   ```
2. Confirm an active billing account is linked to `<GCP_PROJECT_ID>` in the GCP Console (or `gcloud billing projects describe "<GCP_PROJECT_ID>"`).
3. Enable the Compute Engine API:
   ```bash
   gcloud services enable compute.googleapis.com --project="<GCP_PROJECT_ID>"
   ```
4. Ensure you have your operator public IP `/32` CIDR for SSH (`<ADMIN_SSH_CIDR>`, e.g., `$(curl -s https://ifconfig.me)/32`).

---

## 2. Provision Infrastructure (`infra/gcp/provision.sh`)

### Step 2.1 — Generate Required Secrets & Export Inputs

Both `ADMIN_TOKEN` and `WORKER_SECRET` must be at least **32 characters** long. There are **no default or fallback secret values** in any GCP script; `provision.sh`, `startup-controller.sh`, and `startup-worker.sh` fail immediately if missing.

```bash
export GCP_PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
export GCP_REGION="us-central1"
export GCP_ZONE="us-central1-a"

# Dedicated private RFC1918 VPC subnet CIDR and strict operator SSH CIDR (never 0.0.0.0/0):
export SUBNET_CIDR="<VPC_SUBNET_CIDR>"
export ADMIN_SSH_CIDR="$(curl -s https://ifconfig.me)/32"

# Generate fresh >= 32-char secrets (never commit or echo them):
export ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export WORKER_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Optional: git URL so VMs clone into /opt/cloudbalance automatically on first boot
export REPO_URL="https://github.com/<ORG>/<REPO>.git"
export REPO_REF="main"
```

### Step 2.2 — Create VPC, NAT, Firewalls, Static IP & 4 VMs

```bash
bash infra/gcp/provision.sh
```

**Provisioning order executed by `infra/gcp/provision.sh`:**
1. Creates dedicated VPC `cloudbalance-net` and subnet `cloudbalance-subnet` (`--enable-private-ip-google-access`).
2. Reserves static external IP `cloudbalance-controller-ip` and creates Cloud Router (`cloudbalance-router`) + Cloud NAT (`cloudbalance-nat`) so private `--no-address` workers can run `apt-get` / `pip install`.
3. Creates perimeter firewall rules:
   - `FW_CONTROLLER_HTTP` (`cloudbalance-allow-controller-http`): internet (`0.0.0.0/0`) -> `cb-controller` `tcp:80,tcp:443` **only** (port `8000` is **never** opened externally).
   - `FW_CONTROLLER_SSH` (`cloudbalance-allow-controller-ssh`): `<ADMIN_SSH_CIDR>` -> `cb-controller` `tcp:22`.
4. Creates Controller VM (`cloudbalance-controller`, `e2-standard-2`) with `<CONTROLLER_STATIC_EXTERNAL_IP>` and reads `<CONTROLLER_INTERNAL_IP>` via `gcloud compute instances describe`.
5. Creates 3 Worker VMs (`cloudbalance-worker-1..3`, `e2-medium`, `--no-address`, tag `cb-worker`) passing `http://<CONTROLLER_INTERNAL_IP>:8000` and `WORKER_SECRET`, then reads `<WORKER_1..3_INTERNAL_IP>` via `gcloud compute instances describe`.
6. Updates Controller VM metadata with `worker-urls` (`http://<WORKER_1..3_INTERNAL_IP>:8001`) and creates internal firewall rules:
   - `FW_WORKERS_TO_CONTROLLER` (`cloudbalance-allow-workers-to-controller`): worker internal `/32` IPs -> `cb-controller` `tcp:8000`.
   - `FW_CONTROLLER_TO_WORKERS` (`cloudbalance-allow-controller-to-workers`): `<CONTROLLER_INTERNAL_IP>/32` -> `cb-worker` `tcp:8001`.

**VM Startup & Systemd Order:**
- **Controller VM (`startup-controller.sh`):** resolves secrets without defaults, writes `/etc/cloudbalance/controller.env` (`chmod 600`, `CB_LOCAL_MODE="true"`, `CB_SEED_DEMO_WORKERS="false"`), configures `/etc/logrotate.d/cloudbalance` on `/var/lib/cloudbalance/data/*.csv` & `*.log`, installs `backend/requirements.txt` into `/opt/cloudbalance/venv` + runs `pip check`, configures Nginx from [deploy/nginx/nginx.conf](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/deploy/nginx/nginx.conf), and starts `cloudbalance-controller.service` (`--workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1`, independent of workers/Redis/Mongo).
- **Worker VMs (`startup-worker.sh`):** resolves `WORKER_SECRET` (never receives `ADMIN_TOKEN`), writes `/etc/cloudbalance/worker.env` (`chmod 600`), installs `worker/requirements.txt` + runs `pip check`, configures `/etc/logrotate.d/cloudbalance-worker`, and after `network-online.target` starts `cloudbalance-worker-executor.service` (`:8001`) followed by `cloudbalance-worker-agent.service` (`--interval 1.5`).
- *(If `REPO_URL` was left empty, upload the repo to `/opt/cloudbalance` on the VMs via `scp` / Bastion and re-run `startup-controller.sh` and `startup-worker.sh`.)*

### Step 2.3 — Read Real Assigned IPs

```bash
gcloud compute instances list \
  --project="${GCP_PROJECT_ID}" \
  --filter="name~'^cloudbalance-'" \
  --format="table(name,zone,machineType.basename(),networkInterfaces[0].networkIP:label=INTERNAL_IP,networkInterfaces[0].accessConfigs[0].natIP:label=EXTERNAL_IP,status)"
```

Verify that `cloudbalance-worker-1`, `cloudbalance-worker-2`, and `cloudbalance-worker-3` have **no** `EXTERNAL_IP` and that `cloudbalance-controller`'s `INTERNAL_IP` differs from its `EXTERNAL_IP`.

---

## 3. Pre-Share Smoke Test (Run FROM the Controller VM First)

Always run `preflight.py` and `smoke_test.py` **from inside `cloudbalance-controller`** against the Controller/Worker internal IPs **before** sharing the public `/client` URL with anyone:

```bash
gcloud compute ssh cloudbalance-controller --zone="${GCP_ZONE}" --project="${GCP_PROJECT_ID}"
```

On `cloudbalance-controller`:

```bash
set -a
source /etc/cloudbalance/controller.env
set +a

# 1. Verify Controller service, Nginx config, and environment contract
sudo systemctl status cloudbalance-controller nginx --no-pager
sudo nginx -t
/opt/cloudbalance/venv/bin/python /opt/cloudbalance/scripts/preflight.py \
  --env-file /etc/cloudbalance/controller.env

# 2. Verify all 3 private Worker VMs respond directly over VPC internal IPs (:8001)
for url in ${WORKER_URLS//,/ }; do
  echo "Checking ${url}/healthz ..."
  curl -sf "${url}/healthz"
  echo
done

# 3. Verify health, auth gates, /ws, live telemetry (3 workers), and light/heavy POST /tasks
/opt/cloudbalance/venv/bin/python /opt/cloudbalance/scripts/smoke_test.py \
  --controller "${CONTROLLER_URL}"

# 4. Verify Nginx reverse proxy on localhost (:80)
curl -sf http://127.0.0.1/healthz
curl -sf http://127.0.0.1/ready
```

Only proceed once `/ready` shows all 3 active workers and `smoke_test.py` prints `ALL SMOKE TEST CHECKS PASSED!`.

---

## 4. Sharing `/client` Safely & Keeping `/ops` Private

> [!WARNING]
> **Plain-HTTP Token Exposure Warning:** Plain HTTP (`http://<CONTROLLER_STATIC_EXTERNAL_IP>`) transmits `Authorization: Bearer <ADMIN_TOKEN>` and `/ws?token=...` **unencrypted** across the network. **Do not** authenticate to `/ops` or `/benchmark` over untrusted HTTP networks without TLS and/or IP restriction.

**Public Demo Routes (stay open):**
- `http://<CONTROLLER_STATIC_EXTERNAL_IP>/` — Public Workload Portal
- `http://<CONTROLLER_STATIC_EXTERNAL_IP>/client?id=client-1` (and `client-2`, `client-3`) — Public Browser Poisson Client
- `POST /tasks`, `GET /test/status`, `GET /healthz`

**Keep Admin Routes (`/ops`, `/benchmark`, `/admin/`, `/api/v1/control`, `/api/v1/telemetry`, `/api/v1/benchmark`) Private using ONE of:**

1. **Option A — Nginx `ALLOWED_ADMIN_CIDR` Allowlist (Fastest on HTTP VM):**
   On `cloudbalance-controller`, edit `/etc/nginx/sites-available/cloudbalance` (from [deploy/nginx/nginx.conf](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/deploy/nginx/nginx.conf)) and uncomment the `# allow <ALLOWED_ADMIN_CIDR>;` / `# deny all;` lines inside:
   - `location /admin/`
   - `location /api/v1/control`
   - `location /api/v1/telemetry`
   - `location /api/v1/benchmark`
   - `location = /ops`
   - `location = /benchmark`
   Replace `<ALLOWED_ADMIN_CIDR>` with your operator IP `/32`, then reload Nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
   Reviewers can use `/` and `/client`, while `/ops` returns `403 Forbidden` to anyone outside `<ALLOWED_ADMIN_CIDR>`.

2. **Option B — HTTPS / Cloudflare Tunnel (`cloudflared`):**
   - Put TLS + Cloudflare Access in front of `http://127.0.0.1:80` (or `127.0.0.1:8000`), update `CB_ALLOWED_ORIGINS="https://<YOUR_DOMAIN>"` in `/etc/cloudbalance/controller.env`, and restart `cloudbalance-controller.service`.
   - Gate `/ops`, `/benchmark`, `/admin/*`, `/api/v1/control/*`, `/api/v1/telemetry/*`, `/api/v1/benchmark/*` with Cloudflare Access identity rules while leaving `/`, `/client`, `/tasks`, `/test/status`, `/healthz` public.

---

## 5. What to Do If a Worker VM Is Down

1. **Expected Controller & Scheduler Behavior (`backend/app/api/tasks.py` & `cluster_state.py`):**
   - **Controller stays online:** `cloudbalance-controller.service` has zero systemd dependency on worker services and runs with `CB_SEED_DEMO_WORKERS="false"`, so virtual fallback workers are never substituted.
   - **MILP (`ortools_milp`):** Once the down worker stops sending `1.5s` heartbeats, its TTL entry expires after `CB_WORKER_TTL_SECONDS` (`10`s) — or is immediately evicted on HTTP `ConnectError`/`NetworkError` — so MILP routes tasks exclusively to surviving workers.
   - **Round Robin (`round_robin`):** Atomic `rr_counter` still cycles over `WORKER_URLS`. On dispatch to a downed worker, **only HTTP connection/network failures (`ConnectError`/`NetworkError`)** trigger `evict_worker()` and a single cyclic failover to the next alive worker (`failover=true` in `test_log.csv`). HTTP `503` (queue full) or `504`/`408` timeouts do **not** evict or fail over.
2. **Automatic Re-Admission Upon Recovery:**
   - Fix or restart the worker (`sudo systemctl restart cloudbalance-worker-executor cloudbalance-worker-agent` or start/reset the Compute Engine instance).
   - As soon as `cloudbalance-worker-agent.service` sends its next `1.5s` heartbeat (`POST /api/v1/telemetry`), the Controller re-writes `cluster:worker:{worker_id}` and automatically re-admits the worker into both MILP and `/ready` without restarting the Controller.

---

## 6. Rollback Procedure

### Rollback Application / Config Changes on Existing VMs
1. Restore the previous git revision/directory in `/opt/cloudbalance` and previous `/etc/cloudbalance/*.env` backup (`chmod 600`).
2. Re-run preflight + nginx validation:
   ```bash
   /opt/cloudbalance/venv/bin/python /opt/cloudbalance/scripts/preflight.py --env-file /etc/cloudbalance/controller.env
   sudo nginx -t && sudo systemctl reload nginx
   sudo systemctl restart cloudbalance-controller.service
   ```

### Full Infrastructure Rollback
Delete all provisioned CloudBalance GCP resources immediately using [infra/gcp/teardown.sh](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/infra/gcp/teardown.sh).

---

## 7. Mandatory Teardown After Review (Cost Control)

> [!CAUTION]
> **Run `teardown.sh` immediately once the demo/review finishes** so idle VMs (`4` instances + boot disks), Cloud NAT gateway + NAT external IP, and reserved static external IP stop accruing charges.

```bash
export GCP_PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
export GCP_REGION="us-central1"
export GCP_ZONE="us-central1-a"
bash infra/gcp/teardown.sh
```

**Scope guarantee:** `infra/gcp/teardown.sh` deletes **only** the dedicated CloudBalance resources created by `infra/gcp/provision.sh`:
- `4` VMs (`cloudbalance-controller`, `cloudbalance-worker-1`, `cloudbalance-worker-2`, `cloudbalance-worker-3`)
- Reserved Static External IP (`cloudbalance-controller-ip`)
- Cloud NAT (`cloudbalance-nat`) + Cloud Router (`cloudbalance-router`)
- All `4` named firewall rules (`FW_CONTROLLER_HTTP`, `FW_CONTROLLER_SSH`, `FW_WORKERS_TO_CONTROLLER`, `FW_CONTROLLER_TO_WORKERS`)
- Dedicated subnet (`cloudbalance-subnet`) + dedicated VPC (`cloudbalance-net`)

At the end, `teardown.sh` lists any remaining resources matching `name~'^cloudbalance-'` across instances, addresses, routers, firewall rules, subnets, and VPCs so you can verify a clean zero-billing state.
