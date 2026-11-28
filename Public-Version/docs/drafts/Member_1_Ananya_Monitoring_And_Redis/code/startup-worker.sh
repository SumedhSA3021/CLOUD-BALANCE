#!/usr/bin/env bash
# Startup script for CloudBalance Internal Worker VM (Ubuntu 22.04)
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3-pip curl

META_URL="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
META_HDR="Metadata-Flavor: Google"

WORKER_ID="$(curl -sf -H "${META_HDR}" "${META_URL}/worker-id" || hostname)"
WORKER_IP="$(curl -sf -H "${META_HDR}" "${META_URL}/worker-ip" || hostname -I | awk '{print $1}')"
CONTROLLER_URL="$(curl -sf -H "${META_HDR}" "${META_URL}/controller-url" || echo "http://10.128.0.10:8000")"
CB_API_KEY="$(curl -sf -H "${META_HDR}" "${META_URL}/cb-api-key" || echo "")"

mkdir -p /etc/cloudbalance /opt/cloudbalance
cat <<EOF >/etc/cloudbalance/worker.env
WORKER_ID=${WORKER_ID}
WORKER_IP=${WORKER_IP}
WORKER_PORT=8001
CONTROLLER_URL=${CONTROLLER_URL}
CB_API_KEY=${CB_API_KEY}
EOF
chmod 600 /etc/cloudbalance/worker.env

if [[ -d /opt/cloudbalance/worker ]]; then
  python3.11 -m venv /opt/cloudbalance/venv
  /opt/cloudbalance/venv/bin/pip install --upgrade pip
  /opt/cloudbalance/venv/bin/pip install -r /opt/cloudbalance/worker/requirements.txt
  cp /opt/cloudbalance/infra/systemd/cloudbalance-worker-executor.service /etc/systemd/system/
  cp /opt/cloudbalance/infra/systemd/cloudbalance-worker-agent.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now cloudbalance-worker-executor.service
  systemctl enable --now cloudbalance-worker-agent.service
fi

