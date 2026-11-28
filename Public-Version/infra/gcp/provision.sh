#!/usr/bin/env bash
# =============================================================================
# CloudBalance GCP Compute Engine Provisioning Script (Ubuntu 22.04 / 24.04)
#
# Topology:
#   - 1 Controller VM (e2-standard-2) with reserved STATIC EXTERNAL IP + VPC INTERNAL IP
#   - 3 Private Worker VMs (e2-medium, --no-address) communicating ONLY inside the VPC
#   - Cloud Router + Cloud NAT for worker outbound package installs (pip/apt)
#   - 4 Named Firewall Rules (controller port 8000 is NEVER exposed to the internet)
#
# Required Environment Variables:
#   GCP_PROJECT_ID   : Target GCP project ID
#   ADMIN_SSH_CIDR   : Operator /32 CIDR allowed for SSH (never 0.0.0.0/0)
#   SUBNET_CIDR      : Private VPC CIDR range (e.g. a RFC1918 /20 CIDR)
#   ADMIN_TOKEN      : Controller admin secret (>= 32 chars; generate locally, never commit)
#   WORKER_SECRET    : Shared telemetry HMAC/header secret (>= 32 chars; never commit)
#
# Generate secrets locally before running:
#   export ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
#   export WORKER_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
# =============================================================================
set -euo pipefail
set +x

PROJECT_ID="${GCP_PROJECT_ID:?ERROR: Set GCP_PROJECT_ID environment variable}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"

VPC_NAME="cloudbalance-net"
SUBNET_NAME="cloudbalance-subnet"
SUBNET_CIDR="${SUBNET_CIDR:-<VPC_SUBNET_CIDR>}"
STATIC_IP_NAME="cloudbalance-controller-ip"
ROUTER_NAME="cloudbalance-router"
NAT_NAME="cloudbalance-nat"

CONTROLLER_TAG="cb-controller"
WORKER_TAG="cb-worker"
CONTROLLER_VM="cloudbalance-controller"
WORKER_VMS=("cloudbalance-worker-1" "cloudbalance-worker-2" "cloudbalance-worker-3")

# Named Firewall Rules (referenced consistently in teardown.sh)
FW_CONTROLLER_HTTP="cloudbalance-allow-controller-http"
FW_CONTROLLER_SSH="cloudbalance-allow-controller-ssh"
FW_WORKERS_TO_CONTROLLER="cloudbalance-allow-workers-to-controller"
FW_CONTROLLER_TO_WORKERS="cloudbalance-allow-controller-to-workers"

ADMIN_SSH_CIDR="${ADMIN_SSH_CIDR:-<ADMIN_SSH_CIDR>}"
REPO_URL="${REPO_URL:-}"
REPO_REF="${REPO_REF:-main}"
SERVICE_USER="${SERVICE_USER:-cloudbalance}"
SERVICE_GROUP="${SERVICE_GROUP:-cloudbalance}"

# Validate mandatory operator inputs cleanly without printing secret values
if [[ -z "${ADMIN_SSH_CIDR}" || "${ADMIN_SSH_CIDR}" == *"<"* ]]; then
  echo "ERROR: ADMIN_SSH_CIDR is required (set it to your public IP /32 CIDR)." >&2
  exit 1
fi
if [[ "${ADMIN_SSH_CIDR}" == *"0.0.0.0/0"* ]]; then
  echo "ERROR: ADMIN_SSH_CIDR must never be 0.0.0.0/0." >&2
  exit 1
fi
if [[ -z "${SUBNET_CIDR}" || "${SUBNET_CIDR}" == *"<"* ]]; then
  echo "ERROR: SUBNET_CIDR is required (e.g. export SUBNET_CIDR='<VPC_SUBNET_CIDR>' replaced with your private /20 range)." >&2
  exit 1
fi
if [[ -z "${ADMIN_TOKEN:-}" || "${ADMIN_TOKEN}" == *"<"* || ${#ADMIN_TOKEN} -lt 32 ]]; then
  echo "ERROR: ADMIN_TOKEN must be exported and at least 32 characters long (no default fallback)." >&2
  exit 1
fi
if [[ -z "${WORKER_SECRET:-}" || "${WORKER_SECRET}" == *"<"* || ${#WORKER_SECRET} -lt 32 ]]; then
  echo "ERROR: WORKER_SECRET must be exported and at least 32 characters long (no default fallback)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/7] Creating VPC (${VPC_NAME}) and private Subnet (${SUBNET_NAME})..."
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

echo "==> [2/7] Reserving Static External IP (${STATIC_IP_NAME}) and creating Cloud Router + NAT..."
gcloud compute addresses create "${STATIC_IP_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}"

CONTROLLER_STATIC_EXTERNAL_IP="$(gcloud compute addresses describe "${STATIC_IP_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='get(address)')"

gcloud compute routers create "${ROUTER_NAME}" \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --region="${REGION}"

gcloud compute routers nats create "${NAT_NAME}" \
  --project="${PROJECT_ID}" \
  --router="${ROUTER_NAME}" \
  --region="${REGION}" \
  --nat-all-subnet-ip-ranges \
  --auto-allocate-nat-external-ips

echo "==> [3/7] Creating perimeter firewall rules (${FW_CONTROLLER_HTTP}, ${FW_CONTROLLER_SSH})..."
# (a) Internet -> Controller HTTP/HTTPS (ports 80 and 443 only; controller API port stays internal-only)
gcloud compute firewall-rules create "${FW_CONTROLLER_HTTP}" \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=ALLOW \
  --rules=tcp:80,tcp:443 \
  --source-ranges="0.0.0.0/0" \
  --target-tags="${CONTROLLER_TAG}"

# (d) Operator SSH -> Controller restricted strictly to ADMIN_SSH_CIDR
gcloud compute firewall-rules create "${FW_CONTROLLER_SSH}" \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=ALLOW \
  --rules=tcp:22 \
  --source-ranges="${ADMIN_SSH_CIDR}" \
  --target-tags="${CONTROLLER_TAG}"

echo "==> [4/7] Provisioning Controller VM (${CONTROLLER_VM})..."
gcloud compute instances create "${CONTROLLER_VM}" \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --machine-type=e2-standard-2 \
  --subnet="${SUBNET_NAME}" \
  --address="${CONTROLLER_STATIC_EXTERNAL_IP}" \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-balanced \
  --tags="${CONTROLLER_TAG}" \
  --metadata="admin-token=${ADMIN_TOKEN},worker-secret=${WORKER_SECRET},controller-static-external-ip=${CONTROLLER_STATIC_EXTERNAL_IP},repo-url=${REPO_URL},repo-ref=${REPO_REF},service-user=${SERVICE_USER},service-group=${SERVICE_GROUP}" \
  --metadata-from-file="startup-script=${SCRIPT_DIR}/startup-controller.sh"

# Read the assigned VPC INTERNAL IP separately from the STATIC EXTERNAL IP at runtime
CONTROLLER_INTERNAL_IP="$(gcloud compute instances describe "${CONTROLLER_VM}" \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --format='get(networkInterfaces[0].networkIP)')"

if [[ -z "${CONTROLLER_INTERNAL_IP}" || -z "${CONTROLLER_STATIC_EXTERNAL_IP}" ]]; then
  echo "ERROR: Failed to read controller internal or static external IP from gcloud." >&2
  exit 1
fi
if [[ "${CONTROLLER_INTERNAL_IP}" == "${CONTROLLER_STATIC_EXTERNAL_IP}" ]]; then
  echo "ERROR: Controller internal IP must never equal static external IP." >&2
  exit 1
fi

echo "==> [5/7] Provisioning 3 Private Worker VMs (--no-address, tag ${WORKER_TAG})..."
for IDX in 1 2 3; do
  WVM="cloudbalance-worker-${IDX}"
  gcloud compute instances create "${WVM}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --machine-type=e2-medium \
    --subnet="${SUBNET_NAME}" \
    --no-address \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-balanced \
    --tags="${WORKER_TAG}" \
    --metadata="worker-id=worker-${IDX},controller-internal-ip=${CONTROLLER_INTERNAL_IP},controller-url=http://${CONTROLLER_INTERNAL_IP}:8000,worker-secret=${WORKER_SECRET},repo-url=${REPO_URL},repo-ref=${REPO_REF},service-user=${SERVICE_USER},service-group=${SERVICE_GROUP}" \
    --metadata-from-file="startup-script=${SCRIPT_DIR}/startup-worker.sh"
done

WORKER_INTERNAL_IPS=()
WORKER_CIDRS=()
WORKER_URL_LIST=()
for WVM in "${WORKER_VMS[@]}"; do
  WIP="$(gcloud compute instances describe "${WVM}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --format='get(networkInterfaces[0].networkIP)')"
  if [[ -z "${WIP}" ]]; then
    echo "ERROR: Failed to read internal IP for ${WVM}." >&2
    exit 1
  fi
  WORKER_INTERNAL_IPS+=("${WIP}")
  WORKER_CIDRS+=("${WIP}/32")
  WORKER_URL_LIST+=("http://${WIP}:8001")
done

WORKER_SOURCE_CIDRS="$(IFS=,; echo "${WORKER_CIDRS[*]}")"
WORKER_URLS="$(IFS=,; echo "${WORKER_URL_LIST[*]}")"

echo "==> [6/7] Updating Controller metadata with worker endpoints and creating VPC-internal firewall rules..."
gcloud compute instances add-metadata "${CONTROLLER_VM}" \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --metadata="controller-internal-ip=${CONTROLLER_INTERNAL_IP},worker-urls=${WORKER_URLS}"

# (b) Worker internal IPs -> Controller tcp:8000 ONLY (telemetry heartbeats).
# Uses exact worker internal /32 ranges rather than OR-combining --source-tags with --source-ranges.
gcloud compute firewall-rules create "${FW_WORKERS_TO_CONTROLLER}" \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=ALLOW \
  --rules=tcp:8000 \
  --source-ranges="${WORKER_SOURCE_CIDRS}" \
  --target-tags="${CONTROLLER_TAG}"

# (c) Controller INTERNAL IP -> Worker VMs tcp:8001 ONLY (task execution dispatch)
gcloud compute firewall-rules create "${FW_CONTROLLER_TO_WORKERS}" \
  --project="${PROJECT_ID}" \
  --network="${VPC_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=ALLOW \
  --rules=tcp:8001 \
  --source-ranges="${CONTROLLER_INTERNAL_IP}/32" \
  --target-tags="${WORKER_TAG}"

echo "==> [7/7] Provisioning Summary (Secrets omitted)"
echo "---------------------------------------------------------------------"
echo "Controller Public Static IP : ${CONTROLLER_STATIC_EXTERNAL_IP}"
echo "Client / Dashboard Origin   : http://${CONTROLLER_STATIC_EXTERNAL_IP}"
echo "Laptop Client Page          : http://${CONTROLLER_STATIC_EXTERNAL_IP}/client"
echo "Controller Internal VPC IP  : ${CONTROLLER_INTERNAL_IP}"
for IDX in 0 1 2; do
  echo "Worker-$((IDX + 1)) Internal VPC IP     : ${WORKER_INTERNAL_IPS[$IDX]}:8001 (No Public IP)"
done
echo "Firewall Rules              : ${FW_CONTROLLER_HTTP}, ${FW_CONTROLLER_SSH}, ${FW_WORKERS_TO_CONTROLLER}, ${FW_CONTROLLER_TO_WORKERS}"
echo "Allowed Admin SSH CIDR      : ${ADMIN_SSH_CIDR}"
echo "---------------------------------------------------------------------"
