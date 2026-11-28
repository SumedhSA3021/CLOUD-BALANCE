#!/usr/bin/env bash
# =============================================================================
# Startup script for CloudBalance Controller VM (Ubuntu 22.04 / 24.04)
#
# Python Version Notice:
#   - backend/requirements.txt pins were verified locally ONLY on Python 3.14.
#   - Python 3.11 / 3.12 compatibility is NOT verified locally and is checked on
#     the VM below via `python3 --version`, `pip install`, and `pip check`.
#
# Security & Mode Defaults:
#   - CB_LOCAL_MODE="true" with ONE uvicorn worker (--workers 1) is the tested mode.
#   - CB_SEED_DEMO_WORKERS="false" guarantees routing only to real Worker VMs.
#   - ADMIN_TOKEN and WORKER_SECRET must exist (env or metadata); never echoed or defaulted.
# =============================================================================
set -euo pipefail
set +x

APP_DIR="${APP_DIR:-/opt/cloudbalance}"
VENV_DIR="${VENV_DIR:-/opt/cloudbalance/venv}"
DATA_DIR="/var/lib/cloudbalance/data"
ENV_FILE="/etc/cloudbalance/controller.env"
META_URL="http://metadata.google.internal/computeMetadata/v1/instance"
META_HDR="Metadata-Flavor: Google"

fetch_attr() {
  local key="$1"
  curl -sf --max-time 3 -H "${META_HDR}" "${META_URL}/attributes/${key}" 2>/dev/null || true
}

fetch_net_meta() {
  local path="$1"
  curl -sf --max-time 3 -H "${META_HDR}" "${META_URL}/${path}" 2>/dev/null || true
}

SERVICE_USER="${SERVICE_USER:-$(fetch_attr service-user)}"
SERVICE_GROUP="${SERVICE_GROUP:-$(fetch_attr service-group)}"
SERVICE_USER="${SERVICE_USER:-cloudbalance}"
SERVICE_GROUP="${SERVICE_GROUP:-cloudbalance}"
REPO_URL="${REPO_URL:-$(fetch_attr repo-url)}"
REPO_REF="${REPO_REF:-$(fetch_attr repo-ref)}"
REPO_REF="${REPO_REF:-main}"

# Resolve required secrets without fallback defaults and never echo them
if [[ -z "${ADMIN_TOKEN:-}" ]]; then
  ADMIN_TOKEN="$(fetch_attr admin-token)"
fi
if [[ -z "${WORKER_SECRET:-}" ]]; then
  WORKER_SECRET="$(fetch_attr worker-secret)"
fi
if [[ -z "${ADMIN_TOKEN}" || "${ADMIN_TOKEN}" == *"<"* || ${#ADMIN_TOKEN} -lt 32 ]]; then
  echo "ERROR: ADMIN_TOKEN is missing or < 32 chars (no insecure default allowed)." >&2
  exit 1
fi
if [[ -z "${WORKER_SECRET}" || "${WORKER_SECRET}" == *"<"* || ${#WORKER_SECRET} -lt 32 ]]; then
  echo "ERROR: WORKER_SECRET is missing or < 32 chars (no insecure default allowed)." >&2
  exit 1
fi

# Clearly separate Controller INTERNAL VPC IP from STATIC EXTERNAL IP
CONTROLLER_INTERNAL_IP="${CONTROLLER_INTERNAL_IP:-$(fetch_attr controller-internal-ip)}"
if [[ -z "${CONTROLLER_INTERNAL_IP}" ]]; then
  CONTROLLER_INTERNAL_IP="$(fetch_net_meta network-interfaces/0/ip)"
fi
CONTROLLER_STATIC_EXTERNAL_IP="${CONTROLLER_STATIC_EXTERNAL_IP:-$(fetch_attr controller-static-external-ip)}"
if [[ -z "${CONTROLLER_STATIC_EXTERNAL_IP}" ]]; then
  CONTROLLER_STATIC_EXTERNAL_IP="$(fetch_net_meta network-interfaces/0/access-configs/0/external-ip)"
fi

if [[ -z "${CONTROLLER_INTERNAL_IP}" || "${CONTROLLER_INTERNAL_IP}" == *"<"* ]]; then
  echo "ERROR: CONTROLLER_INTERNAL_IP could not be resolved from env or instance metadata." >&2
  exit 1
fi
if [[ -z "${CONTROLLER_STATIC_EXTERNAL_IP}" || "${CONTROLLER_STATIC_EXTERNAL_IP}" == *"<"* ]]; then
  echo "ERROR: CONTROLLER_STATIC_EXTERNAL_IP could not be resolved from env or instance metadata." >&2
  exit 1
fi
if [[ "${CONTROLLER_INTERNAL_IP}" == "${CONTROLLER_STATIC_EXTERNAL_IP}" ]]; then
  echo "ERROR: CONTROLLER_INTERNAL_IP and CONTROLLER_STATIC_EXTERNAL_IP must differ." >&2
  exit 1
fi

# Wait briefly for provision.sh to populate worker-urls metadata after creating worker VMs
WORKER_URLS="${WORKER_URLS:-}"
if [[ -z "${WORKER_URLS}" ]]; then
  for _attempt in $(seq 1 24); do
    WORKER_URLS="$(fetch_attr worker-urls)"
    if [[ -n "${WORKER_URLS}" ]]; then
      break
    fi
    sleep 5
  done
fi
if [[ -z "${WORKER_URLS}" || "${WORKER_URLS}" == *"<"* ]]; then
  echo "ERROR: WORKER_URLS is required (private worker internal http://<WORKER_IP>:8001 list)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y nginx logrotate git curl ca-certificates

# Detect or install Python 3.12 / 3.11 (pins are verified on VM via pip check below)
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
      PYTHON_BIN="${candidate}"
      break
    fi
  fi
done
if [[ -z "${PYTHON_BIN}" ]]; then
  apt-get install -y python3.11 python3.11-venv python3-pip || apt-get install -y python3.12 python3.12-venv python3-pip
  PYTHON_BIN="$(command -v python3.12 || command -v python3.11)"
else
  PY_VER="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  apt-get install -y "python${PY_VER}-venv" python3-pip || apt-get install -y python3-venv python3-pip
fi
echo "==> Controller VM Python check: $("${PYTHON_BIN}" --version) (pins unverified locally below 3.14; checking on VM via pip check)"

if ! getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
  groupadd --system "${SERVICE_GROUP}"
fi
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${SERVICE_GROUP}" --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

if [[ ! -d "${APP_DIR}/backend" && -n "${REPO_URL}" ]]; then
  git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" "${APP_DIR}"
fi

install -d -m 750 -o root -g root /etc/cloudbalance
install -d -m 750 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${DATA_DIR}"

# Write /etc/cloudbalance/controller.env safely with chmod 600 (never echo secrets)
(
  umask 077
  cat >"${ENV_FILE}" <<EOF
ADMIN_TOKEN="${ADMIN_TOKEN}"
WORKER_SECRET="${WORKER_SECRET}"
CB_APP_NAME="CloudBalance Controller"
CB_ENV="production"
CB_LOCAL_MODE="true"
CB_SEED_DEMO_WORKERS="false"
CONTROLLER_HOST="0.0.0.0"
CONTROLLER_PORT="8000"
CONTROLLER_URL="http://${CONTROLLER_INTERNAL_IP}:8000"
WORKER_URLS="${WORKER_URLS}"
CB_ALLOWED_ORIGINS="http://${CONTROLLER_STATIC_EXTERNAL_IP}"
CB_FRONTEND_DIST_DIR="frontend/dist"
CB_DATA_DIR="${DATA_DIR}"
CB_REQUIRE_API_KEY="false"
CB_DEFAULT_SCHEDULER="ortools_milp"
CB_WORKER_TTL_SECONDS="10"
CB_MAX_QUEUE_DEPTH="500"
CB_RATE_LIMIT_PER_SEC="300"
CB_RATE_LIMIT_PER_MIN="2400"
CB_MAX_PAYLOAD_BYTES="65536"
CB_SOLVER_TIME_LIMIT_MS="50"
CB_CPU_CAP_PCT="85.0"
CB_MEM_CAP_PCT="90.0"
CB_DISPATCH_TIMEOUT_SEC="15.0"
CB_DISPATCH_MAX_RETRIES="2"
CB_WS_BROADCAST_INTERVAL_SEC="1.5"
EOF
)
chown root:root "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

# Configure logrotate for controller data directory (CSV/log files above 50MB)
cat >/etc/logrotate.d/cloudbalance <<EOF
${DATA_DIR}/*.csv ${DATA_DIR}/*.log {
    daily
    rotate 7
    size 50M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su ${SERVICE_USER} ${SERVICE_GROUP}
}
EOF
chmod 644 /etc/logrotate.d/cloudbalance

if [[ -f "${APP_DIR}/backend/requirements.txt" ]]; then
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r "${APP_DIR}/backend/requirements.txt"
  "${VENV_DIR}/bin/pip" check

  # Install Nginx config from deploy/nginx/nginx.conf
  cp "${APP_DIR}/deploy/nginx/nginx.conf" /etc/nginx/sites-available/cloudbalance
  sed -i "s|/opt/cloudbalance/frontend/dist|${APP_DIR}/frontend/dist|g" /etc/nginx/sites-available/cloudbalance
  rm -f /etc/nginx/sites-enabled/default
  ln -sf /etc/nginx/sites-available/cloudbalance /etc/nginx/sites-enabled/cloudbalance
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx

  # Install systemd unit from deploy/systemd substituting service placeholders
  sed \
    -e "s|<SERVICE_USER>|${SERVICE_USER}|g" \
    -e "s|<SERVICE_GROUP>|${SERVICE_GROUP}|g" \
    -e "s|<APP_DIR>|${APP_DIR}|g" \
    -e "s|<VENV_DIR>|${VENV_DIR}|g" \
    "${APP_DIR}/deploy/systemd/cloudbalance-controller.service" \
    >/etc/systemd/system/cloudbalance-controller.service
  chmod 644 /etc/systemd/system/cloudbalance-controller.service
  systemctl daemon-reload
  systemctl enable --now cloudbalance-controller.service
else
  echo "INFO: ${APP_DIR}/backend/requirements.txt not present yet; upload repo to ${APP_DIR} and re-run startup-controller.sh."
fi
