#!/usr/bin/env bash
# =============================================================================
# CloudBalance GCP Teardown Script
# Cleanly removes all 4 VMs (controller + 3 workers), static external IP,
# Cloud NAT & Router, all 4 firewall rules, Subnet, and VPC, then lists any
# remaining CloudBalance GCP resources so nothing keeps billing unnoticed.
# =============================================================================
set -euo pipefail
set +x

PROJECT_ID="${GCP_PROJECT_ID:?ERROR: Set GCP_PROJECT_ID environment variable}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"

VPC_NAME="cloudbalance-net"
SUBNET_NAME="cloudbalance-subnet"
STATIC_IP_NAME="cloudbalance-controller-ip"
ROUTER_NAME="cloudbalance-router"
NAT_NAME="cloudbalance-nat"

CONTROLLER_VM="cloudbalance-controller"
WORKER_VMS=("cloudbalance-worker-1" "cloudbalance-worker-2" "cloudbalance-worker-3")

# Firewall rule names matching provision.sh
FW_CONTROLLER_HTTP="cloudbalance-allow-controller-http"
FW_CONTROLLER_SSH="cloudbalance-allow-controller-ssh"
FW_WORKERS_TO_CONTROLLER="cloudbalance-allow-workers-to-controller"
FW_CONTROLLER_TO_WORKERS="cloudbalance-allow-controller-to-workers"

echo "==> [1/6] Deleting all 4 Compute Engine instances..."
gcloud compute instances delete \
  "${CONTROLLER_VM}" \
  "${WORKER_VMS[@]}" \
  --project="${PROJECT_ID}" \
  --zone="${ZONE}" \
  --quiet || true

echo "==> [2/6] Deleting reserved Static External IP (${STATIC_IP_NAME})..."
gcloud compute addresses delete "${STATIC_IP_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --quiet || true

echo "==> [3/6] Deleting Cloud NAT (${NAT_NAME}) and Cloud Router (${ROUTER_NAME})..."
gcloud compute routers nats delete "${NAT_NAME}" \
  --project="${PROJECT_ID}" \
  --router="${ROUTER_NAME}" \
  --region="${REGION}" \
  --quiet || true

gcloud compute routers delete "${ROUTER_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --quiet || true

echo "==> [4/6] Deleting Firewall rules..."
gcloud compute firewall-rules delete \
  "${FW_CONTROLLER_HTTP}" \
  "${FW_CONTROLLER_SSH}" \
  "${FW_WORKERS_TO_CONTROLLER}" \
  "${FW_CONTROLLER_TO_WORKERS}" \
  --project="${PROJECT_ID}" \
  --quiet || true

echo "==> [5/6] Deleting Subnet (${SUBNET_NAME}) and VPC network (${VPC_NAME})..."
gcloud compute networks subnets delete "${SUBNET_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --quiet || true

gcloud compute networks delete "${VPC_NAME}" \
  --project="${PROJECT_ID}" \
  --quiet || true

echo "==> [6/6] Checking remaining CloudBalance GCP resources in ${PROJECT_ID}..."
FILTER="name~'^cloudbalance-'"
echo "--- Instances ---"
gcloud compute instances list --project="${PROJECT_ID}" --filter="${FILTER}"
echo "--- Addresses ---"
gcloud compute addresses list --project="${PROJECT_ID}" --filter="${FILTER}"
echo "--- Routers ---"
gcloud compute routers list --project="${PROJECT_ID}" --filter="${FILTER}"
echo "--- Firewall Rules ---"
gcloud compute firewall-rules list --project="${PROJECT_ID}" --filter="${FILTER}"
echo "--- Subnets ---"
gcloud compute networks subnets list --project="${PROJECT_ID}" --filter="${FILTER}"
echo "--- VPC Networks ---"
gcloud compute networks list --project="${PROJECT_ID}" --filter="${FILTER}"

echo "==> Teardown and remaining-resource audit complete."
