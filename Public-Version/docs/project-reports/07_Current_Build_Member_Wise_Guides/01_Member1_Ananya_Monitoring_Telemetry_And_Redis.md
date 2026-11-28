# Member 1 (Ananya) — Monitoring, Telemetry Agent & Redis Live State Guide

**Role:** Module 1 — Server Monitoring, `psutil` Telemetry Collection & Redis TTL State Store  
**Technologies:** Python 3.11, `psutil`, `httpx`, Redis (`redis.asyncio` + `InMemoryTTLStore`), GCP Compute Engine (Ubuntu 22.04), `systemd`

---

## 1. Scope & Responsibilities in the Current Build

Member 1 owns the **Sensing & Live State Layer** of CloudBalance. Without accurate, low-latency telemetry from every Worker VM, the OR-Tools MILP scheduler cannot know which server is idle and which server is about to overload.

Your exact responsibilities in the codebase are:
1. **Worker Telemetry Agent (`worker/agent.py`)**: Sampling real OS metrics (`CPU%`, `RAM used/total MB`, `RAM%`, `1-minute load average`, and `active_task_count`) on every worker node every `1.5s–2.0s` and transmitting them to the Controller via `POST /api/v1/telemetry`.
2. **Dual-Mode Redis Client (`backend/app/core/redis_client.py`)**: Storing live worker snapshots in memory using `SETEX cluster:worker:{worker_id} 10 <json>` with a strict **10-second Time-To-Live (TTL)**, with automatic fallback to `InMemoryTTLStore` when running locally without an external Redis server.
3. **Cluster State Service (`backend/app/services/cluster_state.py`)**: Reading active workers (`cluster:worker:*`), combining raw worker telemetry with in-flight reservations, and handling instant worker eviction (`evict_worker`, `kill_worker`, `revive_worker`).
4. **Telemetry Ingestion & Inspection APIs (`backend/app/api/telemetry.py`)**: Exposing `POST /api/v1/telemetry`, `GET /api/v1/telemetry/workers`, and `GET /api/v1/telemetry/redis`.
5. **Cloud Worker VM Provisioning (`infra/gcp/provision.sh`, `infra/gcp/startup-worker.sh`, `infra/systemd/`)**: Provisioning private Ubuntu 22.04 worker VMs on Google Cloud and running the telemetry agent as an auto-restarting `systemd` daemon.

---

## 2. Exact Files Owned by Member 1

| File Path | Key Classes / Functions | Purpose |
| :--- | :--- | :--- |
| [`worker/agent.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/worker/agent.py) | `sample_worker_telemetry()`, `WorkerTelemetryAgent` | Samples `psutil` CPU/RAM/load + active tasks and POSTs JSON to `/api/v1/telemetry` every 1.5–2s. |
| [`backend/app/core/redis_client.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/core/redis_client.py) | `DualRedisClient`, `InMemoryTTLStore` | Unified async Redis client supporting `setex`, `get`, `keys`, `ttl`, `delete` across real Redis and local in-memory TTL store. |
| [`backend/app/services/cluster_state.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/services/cluster_state.py) | `ClusterStateService` | Manages `cluster:worker:{id}` keys with 10s TTL, builds `WorkerSnapshotItem`s, and handles worker kill/revive/failover eviction. |
| [`backend/app/api/telemetry.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/api/telemetry.py) | `ingest_telemetry()`, `list_workers()`, `inspect_redis_state()` | FastAPI router for `/api/v1/telemetry`, `/api/v1/telemetry/workers`, and `/api/v1/telemetry/redis`. |
| [`infra/gcp/provision.sh`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/infra/gcp/provision.sh) & [`startup-worker.sh`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/infra/gcp/startup-worker.sh) | GCP VPC & Worker VM scripts | Creates `cloudbalance-net` VPC, firewall rules, and private `e2-medium` Ubuntu worker VMs. |

---

## 3. Code & Pipeline Walkthrough

### A. Sampling OS Metrics with `psutil` (`worker/agent.py`)
In [`sample_worker_telemetry()`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/worker/agent.py#L27-L83):
- `psutil.cpu_percent(interval=None)` reads non-blocking kernel CPU utilization.
- `psutil.virtual_memory()` reads total physical RAM (`vm.total`) and used RAM (`vm.used`), converted to megabytes.
- `_get_os_load_avg()` reads 1-minute OS run-queue load via `os.getloadavg()` on Linux (with a safe fallback on Windows).
- When running multiple worker processes on a single local machine (`virtual_profile=True`), it blends real `psutil` host CPU readings with each worker's distinct hardware profile (`worker-1`: 4 GB RAM, `worker-2`: 4 GB RAM, `worker-3`: 8 GB RAM) and active executing task load (`runtime_state.active_cpu_demand_pct` and `active_mem_demand_mb`).

### B. Telemetry Payload Contract (`Telemetry` Schema)
Every heartbeat sent to `POST /api/v1/telemetry` follows this strict Pydantic v2 contract:
```json
{
  "worker_id": "worker-1",
  "ip_address": "127.0.0.1",
  "port": 8001,
  "timestamp": "2026-11-11T18:05:35.120000Z",
  "cpu_percent": 38.25,
  "memory_total_mb": 4096.0,
  "memory_used_mb": 1664.0,
  "memory_percent": 40.63,
  "load_avg_1m": 1.53,
  "active_task_count": 1
}
```

### C. Why Redis with a 10-Second TTL (`SETEX cluster:worker:{id} 10`)?
In [`ClusterStateService.update_telemetry()`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/services/cluster_state.py#L36-L50):
```python
key = self.worker_key(telemetry.worker_id)  # "cluster:worker:worker-1"
payload = telemetry.model_dump_json()
await self._redis.setex(key, self._ttl_seconds, payload)  # TTL = 10 seconds
```
- **O(1) In-Memory Speed**: The micro-batcher runs every 200ms. Reading 3 worker keys from Redis takes `< 1 ms`, whereas querying disk-based databases on every batch would bottleneck the scheduler.
- **Self-Healing Passive Health Check**: Each worker refreshes its key every 1.5–2.0 seconds, resetting its TTL back to `10` seconds. If a worker VM crashes or loses network connectivity, its key automatically vanishes from Redis after 10 seconds—achieving automatic failover with zero manual intervention.

### D. Worker Health Status Thresholds (`compute_worker_status`)
In [`backend/app/models/schemas.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/models/schemas.py#L18-L24):
- **`HEALTHY` (Green)**: `cpu_percent < 60%` AND `memory_percent < 70%`
- **`MODERATE` (Amber)**: `cpu_percent` in `60–84%` OR `memory_percent` in `70–89%`
- **`CRITICAL` (Red)**: `cpu_percent >= 85%` OR `memory_percent >= 90%`

---

## 4. API Endpoints Owned by Member 1

| Method & Path | Description | Sample Response |
| :--- | :--- | :--- |
| `POST /api/v1/telemetry` | Receives worker `psutil` heartbeat and executes `SETEX cluster:worker:{id} 10 <json>`. | `{"accepted": true, "worker_id": "worker-1", "ttl_seconds": 10}` |
| `GET /api/v1/telemetry/workers` | Returns active `WorkerSnapshotItem` list combining Redis state + in-flight load. | `[{"worker_id": "worker-1", "cpu_percent": 13.8, "status": "HEALTHY", ...}]` |
| `GET /api/v1/telemetry/redis` | Live inspector showing all `cluster:*` keys and their remaining `ttl_seconds` in Redis. | `{"redis_backend_mode": "in_memory_ttl", "total_keys": 9, "keys": {...}}` |

---

## 5. Top Viva Questions & Answers for Member 1

1. **Q: Why use Redis for worker telemetry instead of storing it in MongoDB?**  
   **A:** Telemetry is high-frequency, ephemeral state updated every 1.5–2 seconds per worker and read every 200ms by the scheduler. Redis stores keys in RAM with sub-millisecond latency and supports native key expiration (`SETEX` with 10s TTL), so stale/dead workers automatically disappear without background cleanup jobs.
2. **Q: What happens if a Worker VM crashes mid-execution?**  
   **A:** Two mechanisms protect the cluster: (a) if an HTTP dispatch to `:8001/execute` fails, `DispatcherService` immediately calls `cluster_state.evict_worker(worker_id)` (`DELETE cluster:worker:{id}`); (b) even if no task is currently dispatching, the dead worker stops sending heartbeats and its Redis key expires after 10 seconds.
3. **Q: How does the system run locally on a laptop if Redis Server isn't installed?**  
   **A:** `DualRedisClient` (`backend/app/core/redis_client.py`) pings `redis://localhost:6379/0` on startup. If unreachable, it seamlessly falls back to `InMemoryTTLStore`, which implements the exact same async `setex`, `get`, `keys`, `ttl`, and `delete` interface using `time.monotonic()` expiration timestamps.

