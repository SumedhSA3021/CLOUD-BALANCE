#!/usr/bin/env bash
# =============================================================================
# CloudBalance GCP Compute Engine Provisioning Script (Ubuntu 22.04 LTS)
#
# Topology:
#   - Custom VPC: cloudbalance-net (subnet 10.128.0.0/20)
#   - Controller VM: cloudbalance-controller (e2-standard-2, public IP)
#   - Worker VMs: cloudbalance-worker-1, cloudbalance-worker-2 (e2-medium, internal IP ONLY)
#   - Cloud Router + Cloud NAT so internal-only workers can apt/pip install packages
#   - Strict Firewalls:
#       * External SSH/80/443/8000 restricted strictly to ALLOWED_CIDR (never 0.0.0.0/0)
#       * Internal 6379 (Redis) and 8001 (Executor) restricted to VPC CIDR 10.128.0.0/20
# =============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID environment variable}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"
VPC_NAME="cloudbalance-net"
SUBNET_NAME="cloudbalance-subnet"
SUBNET_CIDR="10.128.0.0/20"
CONTROLLER_INTERNAL_IP="10.128.0.10"
WORKER1_INTERNAL_IP="10.128.0.11"
WORKER2_INTERNAL_IP="10.128.0.12"

# Security check: ALLOWED_CIDR must be explicitly provided and NEVER 0.0.0.0/0
ALLOWED_CIDR="${ALLOWED_CIDR:-}"
if [[ -z "${ALLOWED_CIDR}" ]]; then
  echo "ERROR: ALLOWED_CIDR is required (e.g. export ALLOWED_CIDR=\"\$(curl -s https://ifconfig.me)/32\")."
  exit 1
fi
if [[ "${ALLOWED_CIDR}" == *"0.0.0.0/0"* ]]; then
  echo "ERROR: ALLOWED_CIDR must never be 0.0.0.0/0. Specify your campus/hotspot/laptop CIDR."
  exit 1
fi

REDIS_PASSWORD="${REDIS_PASSWORD:-$(openssl rand -hex 16)}"
CB_API_KEY="${CB_API_KEY:-$(openssl rand -hex 16)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/6] Creating VPC ${VPC_NAME} and Subnet ${SUBNET_NAME} (${SUBNET_CIDR})..."
gcloud compute networks create "${VPC_NAME}" \
  --project="${PROJECT_ID}" \
  --subnet-mode=custom \
  --bgp-routing-mode=regional

gcloud compute networks subnets create "${SUBNET_NAME}" \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --region="${REGION}" \
  --range="${SUBNET_CIDR}" \
  --enable-private-ip-google-access

echo "==> [2/6] Configuring Cloud Router & Cloud NAT for private Worker VMs..."
gcloud compute routers create cloudbalance-router \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --region="${REGION}"

gcloud compute routers nats create cloudbalance-nat \
  --project="${PROJECT_ID}" \
  --router=cloudbalance-router \
  --region="${REGION}" \
  --nat-all-subnet-ip-ranges \
  --auto-allocate-nat-external-ips

echo "==> [3/6] Creating locked-down Firewall Rules..."
# External access ONLY from ALLOWED_CIDR to Controller (SSH, HTTP, HTTPS, FastAPI 8000)
gcloud compute firewall-rules create cloudbalance-allow-controller-external \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=ALLOW \
  --rules=tcp:22,tcp:80,tcp:443,tcp:8000 \
  --source-ranges="${ALLOWED_CIDR}" \
  --target-tags="cb-controller"

# Internal VPC access ONLY inside 10.128.0.0/20 for Redis (6379), Worker Executor (8001), Controller API (8000), and SSH
gcloud compute firewall-rules create cloudbalance-allow-internal-vpc \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=ALLOW \
  --rules=tcp:22,tcp:6379,tcp:8000,tcp:8001,icmp \
  --source-ranges="${SUBNET_CIDR}"

echo "==> [4/6] Provisioning Controller VM (e2-standard-2, public IP, internal ${CONTROLLER_INTERNAL_IP})..."
gcloud compute instances create cloudbalance-controller \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --machine-type=e2-standard-2 \
  --subnet="${SUBNET_NAME}" \
  --private-network-ip="${CONTROLLER_INTERNAL_IP}" \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-balanced \
  --tags="cb-controller" \
  --metadata="redis-password=${REDIS_PASSWORD},cb-api-key=${CB_API_KEY},controller-ip=${CONTROLLER_INTERNAL_IP}" \
  --metadata-from-file="startup-script=${SCRIPT_DIR}/startup-controller.sh"

echo "==> [5/6] Provisioning Internal-Only Worker VMs (e2-medium x2, NO public IP)..."
for IDX in 1 2; do
  WIP="10.128.0.1${IDX}"
  gcloud compute instances create "cloudbalance-worker-${IDX}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --machine-type=e2-medium \
    --subnet="${SUBNET_NAME}" \
    --private-network-ip="${WIP}" \
    --no-address \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-balanced \
    --tags="cb-worker" \
    --metadata="worker-id=worker-${IDX},worker-ip=${WIP},controller-url=http://${CONTROLLER_INTERNAL_IP}:8000,cb-api-key=${CB_API_KEY}" \
    --metadata-from-file="startup-script=${SCRIPT_DIR}/startup-worker.sh"
done

CONTROLLER_PUBLIC_IP="$(gcloud compute instances describe cloudbalance-controller \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

echo "==> [6/6] Deployment Complete!"
echo "---------------------------------------------------------------------"
echo "Controller Public URL : http://${CONTROLLER_PUBLIC_IP}"
echo "Laptop Client Page    : http://${CONTROLLER_PUBLIC_IP}/client"
echo "Controller FastAPI    : http://${CONTROLLER_PUBLIC_IP}:8000"
echo "Controller Internal IP: ${CONTROLLER_INTERNAL_IP}"
echo "Worker-1 Internal IP  : ${WORKER1_INTERNAL_IP}:8001 (No Public IP)"
echo "Worker-2 Internal IP  : ${WORKER2_INTERNAL_IP}:8001 (No Public IP)"
echo "Allowed Client CIDR   : ${ALLOWED_CIDR}"
echo "---------------------------------------------------------------------"

