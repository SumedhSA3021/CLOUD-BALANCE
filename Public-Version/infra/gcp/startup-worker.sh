#!/usr/bin/env bash
# =============================================================================
# Startup script for CloudBalance Private Worker VM (Ubuntu 22.04 / 24.04)
#
# Python Version Notice:
#   - worker/requirements.txt pins were verified locally ONLY on Python 3.14.
#   - Python 3.11 / 3.12 compatibility is NOT verified locally and is checked on
#     the VM below via `python3 --version`, `pip install`, and `pip check`.
#
# Security:
#   - Worker VMs have NO external IP (--no-address); outbound pip/apt routes via Cloud NAT.
#   - ADMIN_TOKEN must never be placed on Worker VMs.
#   - WORKER_SECRET must exist (env or metadata); never echoed or defaulted.
# =============================================================================
set -euo pipefail
set +x

APP_DIR="${APP_DIR:-/opt/cloudbalance}"
VENV_DIR="${VENV_DIR:-/opt/cloudbalance/venv}"
ENV_FILE="/etc/cloudbalance/worker.env"
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

if [[ -z "${WORKER_SECRET:-}" ]]; then
  WORKER_SECRET="$(fetch_attr worker-secret)"
fi
if [[ -z "${WORKER_SECRET}" || "${WORKER_SECRET}" == *"<"* || ${#WORKER_SECRET} -lt 32 ]]; then
  echo "ERROR: WORKER_SECRET is missing or < 32 chars (no insecure default allowed)." >&2
  exit 1
fi

WORKER_ID="${WORKER_ID:-$(fetch_attr worker-id)}"
if [[ -z "${WORKER_ID}" ]]; then
  WORKER_ID="$(hostname)"
fi

WORKER_IP="${WORKER_IP:-$(fetch_attr worker-ip)}"
if [[ -z "${WORKER_IP}" ]]; then
  WORKER_IP="$(fetch_net_meta network-interfaces/0/ip)"
fi

CONTROLLER_URL="${CONTROLLER_URL:-$(fetch_attr controller-url)}"
if [[ -z "${CONTROLLER_URL}" ]]; then
  CONTROLLER_INTERNAL_IP="${CONTROLLER_INTERNAL_IP:-$(fetch_attr controller-internal-ip)}"
  if [[ -n "${CONTROLLER_INTERNAL_IP}" && "${CONTROLLER_INTERNAL_IP}" != *"<"* ]]; then
    CONTROLLER_URL="http://${CONTROLLER_INTERNAL_IP}:8000"
  fi
fi

if [[ -z "${WORKER_IP}" || "${WORKER_IP}" == *"<"* ]]; then
  echo "ERROR: WORKER_IP could not be resolved from env or instance metadata." >&2
  exit 1
fi
if [[ -z "${CONTROLLER_URL}" || "${CONTROLLER_URL}" == *"<"* ]]; then
  echo "ERROR: CONTROLLER_URL (Controller INTERNAL IP :8000) is required." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y logrotate git curl ca-certificates

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
echo "==> Worker VM (${WORKER_ID}) Python check: $("${PYTHON_BIN}" --version) (pins unverified locally below 3.14; checking on VM via pip check)"

if ! getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
  groupadd --system "${SERVICE_GROUP}"
fi
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${SERVICE_GROUP}" --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

if [[ ! -d "${APP_DIR}/worker" && -n "${REPO_URL}" ]]; then
  git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" "${APP_DIR}"
fi

install -d -m 750 -o root -g root /etc/cloudbalance
install -d -m 750 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" /var/lib/cloudbalance/data

# Write /etc/cloudbalance/worker.env safely with chmod 600 (never echo WORKER_SECRET)
(
  umask 077
  cat >"${ENV_FILE}" <<EOF
WORKER_SECRET="${WORKER_SECRET}"
WORKER_ID="${WORKER_ID}"
WORKER_IP="${WORKER_IP}"
WORKER_PORT="8001"
CONTROLLER_URL="${CONTROLLER_URL}"
WORKER_ENABLE_AGENT="false"
WORKER_TELEMETRY_INTERVAL="1.5"
WORKER_CONCURRENCY_LIMIT="2"
WORKER_QUEUE_CAPACITY="4"
WORKER_TASK_TIMEOUT_SEC="10.0"
MAX_PAYLOAD_BYTES="65536"
HEAVY_TASK_ITERATIONS="180000"
WORKER_TOTAL_MEM_MB="4096.0"
WORKER_BASE_CPU_PCT="8.0"
WORKER_BASE_MEM_MB="420.0"
WORKER_TIME_SCALE="0.15"
WORKER_MAX_PHYSICAL_DIM="350"
EOF
)
chown root:root "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

# Configure logrotate cleanly for local worker data/log directory if written
cat >/etc/logrotate.d/cloudbalance-worker <<EOF
/var/lib/cloudbalance/data/*.log /var/log/cloudbalance/*.log {
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
chmod 644 /etc/logrotate.d/cloudbalance-worker

if [[ -f "${APP_DIR}/worker/requirements.txt" ]]; then
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r "${APP_DIR}/worker/requirements.txt"
  "${VENV_DIR}/bin/pip" check

  for UNIT in cloudbalance-worker-executor.service cloudbalance-worker-agent.service; do
    sed \
      -e "s|<SERVICE_USER>|${SERVICE_USER}|g" \
      -e "s|<SERVICE_GROUP>|${SERVICE_GROUP}|g" \
      -e "s|<APP_DIR>|${APP_DIR}|g" \
      -e "s|<VENV_DIR>|${VENV_DIR}|g" \
      "${APP_DIR}/deploy/systemd/${UNIT}" \
      >"/etc/systemd/system/${UNIT}"
    chmod 644 "/etc/systemd/system/${UNIT}"
  done

  systemctl daemon-reload
  systemctl enable --now cloudbalance-worker-executor.service
  systemctl enable --now cloudbalance-worker-agent.service
else
  echo "INFO: ${APP_DIR}/worker/requirements.txt not present yet; upload repo to ${APP_DIR} and re-run startup-worker.sh."
fi
