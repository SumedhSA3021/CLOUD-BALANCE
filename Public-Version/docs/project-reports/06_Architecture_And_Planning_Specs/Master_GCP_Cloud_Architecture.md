# CloudBalance: Master GCP Cloud Architecture, Engineering Specification & AI Prompting Guide

**Project Title:** CloudBalance — Adaptive Multi-Resource Cloud Load Balancer using Google OR-Tools  
**System Classification:** Distributed Systems, Mixed-Integer Linear Programming (MILP), Real-Time Telemetry & Reactive Workload Steering  
**Target Infrastructure:** Google Cloud Platform (GCP) Compute Engine VPC + Real-Time External Traffic Generator  

---

## 1. System Master Architecture & Workflow

Traditional load balancers (such as Round-Robin or Least Connections) make blind routing decisions because they treat all requests and servers as identical, failing to consider multi-dimensional resource demands (CPU FLOPs vs. RAM memory buffers). 

**CloudBalance** establishes a closed-loop distributed feedback system:
1. **Physical Worker Nodes (Ubuntu VMs on GCP)** continuously report live CPU %, RAM MB, and active task count via a lightweight OS-level agent (`psutil`).
2. **FastAPI Central Backend** ingests these snapshots and caches them in **Redis** with a 10-second TTL (providing automatic node failure detection).
3. **Traffic Generator (Running on a Client PC)** streams synthetic computational tasks arriving via a mathematical **Poisson Process** ($dt = -\ln(1-U)/\lambda$).
4. **Google OR-Tools Optimization Engine** takes the batch of pending tasks and live server metrics, solving a **Mixed-Integer Linear Program (MILP)** to find the optimal assignment matrix that minimizes the peak server load ($\min Z$) under strict CPU ($\le 85\%$) and RAM ($\le 90\%$) safety caps.
5. **Worker Execution Engine** receives dispatched tasks and executes real **NumPy matrix multiplications (BLAS FLOPs)**, driving genuine physical CPU and RAM load on the VM.
6. **React + Vite Dashboard** receives real-time cluster metrics and assignment feeds over **WebSockets** and renders live gauges, server health status cards, and time-series resource charts.

```
       +-----------------------------------------------------------------------------------+
       |                    MEMBER 2 (Sumedh): TRAFFIC GENERATOR (CLIENT PC)               |
       |  • Poisson Process Engine: dt = -ln(1 - U) / lambda                               |
       |  • Workload Profiles: CPU-bound (FLOPs), RAM-bound (Buffers), Balanced            |
       |  • CLI Controls: Real-time traffic streaming, dynamic lambda burst injection      |
       +-----------------------------------------------------------------------------------+
                                                 │
                                                 │ HTTP POST /api/tasks (Public Internet)
                                                 ▼
=====================================================================================================
               GOOGLE CLOUD PLATFORM (GCP) — CUSTOM VPC NETWORK (`cloudbalance-net`)
=====================================================================================================

  ┌───────────────────────────────────────────────────────────────────────────────────────────────┐
  │                    CONTROLLER INSTANCE: `cloudbalance-controller` (e2-standard-2)              │
  │                    External IP: 34.x.x.x  |  Internal VPC IP: 10.128.0.10                     │
  │                                                                                               │
  │  ┌──────────────────────────────────────────────────┐  ┌───────────────────────────────────┐  │
  │  │ MEMBER 3 (Nafisa): FastAPI Central Backend       │  │ MEMBER 1 (Ananya): Redis Cache    │  │
  │  │ • POST /api/telemetry (Ingests agent data)       │  │ • In-Memory Key-Value Store       │  │
  │  │ • POST /api/tasks (Buffers incoming tasks)       │  │ • Key: `cluster:worker:{id}`      │  │
  │  │ • POST /api/dispatch (Routes tasks to workers)   │  │ • Snapshot TTL: 10 seconds        │  │
  │  │ • WebSocket `/ws/live` (Broadcasts state to UI)  │  │ • Real-time load lookup for solver│  │
  │  └────────────────────────┬─────────────────────────┘  └─────────────────▲─────────────────┘  │
  │                           │                                              │                    │
  │                           │ Calls Solver with batch                      │ Reads live cluster │
  │                           ▼                                              │ CPU & RAM metrics  │
  │  ┌──────────────────────────────────────────────────┐                    │                    │
  │  │ MEMBER 2 (Sumedh): OR-Tools Optimization Engine  │────────────────────┘                    │
  │  │ • Mixed-Integer Linear Programming (MILP / CBC)  │                                         │
  │  │ • Binary Decision Variable: X_ij in {0, 1}       │                                         │
  │  │ • Constraints: Single-assignment, CPU, RAM caps  │                                         │
  │  │ • Objective: Min-Max Peak Load (min Z)           │                                         │
  │  └────────────────────────┬─────────────────────────┘                                         │
  │                           │                                                                   │
  │                           │ Real-time cluster events                                          │
  │                           ▼                                                                   │
  │  ┌──────────────────────────────────────────────────┐  ┌───────────────────────────────────┐  │
  │  │ MEMBER 4 (Shubham): React + Vite Dashboard       │  │ MEMBER 3 (Nafisa): MongoDB Atlas  │  │
  │  │ • Port 3000 (Vite / Nginx Production Server)     │  │ • Persistent historical logging   │  │
  │  │ • Live CPU & RAM gauges, node health indicators  │  │ • Task execution audit trails     │  │
  │  │ • Real-time Chart.js time-series trend lines     │  │ • Latency & benchmark analysis    │  │
  │  │ • Interactive task assignment live ticker        │  │   (OR-Tools vs. Round-Robin)      │  │
  │  └──────────────────────────────────────────────────┘  └───────────────────────────────────┘  │
  └───────────────────────────┬───────────────────────────────────────────────┬───────────────────┘
                              │                                               │
             Internal VPC Call│POST :8001/execute            Internal VPC Call│POST :8001/execute
             Payload: {matrix_dim, duration}                 Payload: {matrix_dim, duration}
                              ▼                                               ▼
  ┌───────────────────────────────────────────────┐   ┌───────────────────────────────────────────────┐
  │   GCP VM 1: `cb-worker-1` (e2-medium)         │   │   GCP VM 2: `cb-worker-2` (e2-medium)         │
  │   Internal IP: 10.128.0.11                    │   │   Internal IP: 10.128.0.12                    │
  │                                               │   │                                               │
  │ • MEMBER 1 (Ananya): psutil Telemetry Agent   │   │ • MEMBER 1 (Ananya): psutil Telemetry Agent   │
  │   - Samples CPU %, RAM MB, loadavg every 2s   │   │   - Samples CPU %, RAM MB, loadavg every 2s   │
  │   - Pushes to Controller: POST /api/telemetry │   │   - Pushes to Controller: POST /api/telemetry │
  │ • WORKER EXECUTOR (:8001)                     │   │ • WORKER EXECUTOR (:8001)                     │
  │   - Executes NumPy BLAS matrix multiplication │   │   - Executes NumPy BLAS matrix multiplication │
  │   - Pushes genuine physical vCPU & RAM stress │   │   - Pushes genuine physical vCPU & RAM stress │
  └───────────────────────────────────────────────┘   └───────────────────────────────────────────────┘
```

---

## 2. Global System Data Contracts & Interfaces

### 2.1. Telemetry Payload Contract (`Worker Agent -> FastAPI -> Redis`)
* **Endpoint:** `POST http://10.128.0.10:8000/api/telemetry`
* **JSON Schema:**
```json
{
  "worker_id": "worker-1",
  "ip_address": "10.128.0.11",
  "timestamp": 1772966400.12,
  "cpu_percent": 42.8,
  "memory_total_mb": 4096.0,
  "memory_used_mb": 1540.0,
  "memory_percent": 37.6,
  "load_avg_1m": 0.65,
  "active_task_count": 2
}
```
* **Redis Key:** `cluster:worker:{worker_id}` (Stored with TTL = 10s).

### 2.2. Task Submission Contract (`Traffic Generator -> FastAPI`)
* **Endpoint:** `POST http://<CONTROLLER_EXTERNAL_IP>:8000/api/tasks`
* **JSON Schema:**
```json
{
  "task_id": "task-b7a12e",
  "type": "CPU_INTENSIVE",
  "cpu_demand_pct": 35.0,
  "mem_demand_mb": 256,
  "duration_sec": 4.0,
  "matrix_dim": 2400,
  "created_at": 1772966405.01
}
```

### 2.3. Task Dispatch Contract (`FastAPI -> Worker VM`)
* **Endpoint:** `POST http://<worker_internal_ip>:8001/execute`
* **JSON Schema:**
```json
{
  "task_id": "task-b7a12e",
  "duration_sec": 4.0,
  "matrix_dim": 2400
}
```

### 2.4. WebSocket Broadcast Contract (`FastAPI -> React Dashboard`)
* **WebSocket Route:** `ws://<CONTROLLER_EXTERNAL_IP>:8000/ws/live`
* **JSON Broadcast Message:**
```json
{
  "event_type": "CLUSTER_SNAPSHOT",
  "timestamp": 1772966406.2,
  "workers": [
    {
      "worker_id": "worker-1",
      "cpu_percent": 42.8,
      "memory_percent": 37.6,
      "memory_used_mb": 1540.0,
      "memory_total_mb": 4096.0,
      "active_tasks": 2,
      "status": "HEALTHY"
    },
    {
      "worker_id": "worker-2",
      "cpu_percent": 78.4,
      "memory_percent": 65.1,
      "memory_used_mb": 2666.0,
      "memory_total_mb": 4096.0,
      "active_tasks": 4,
      "status": "MODERATE"
    }
  ],
  "recent_assignments": [
    {
      "task_id": "task-b7a12e",
      "assigned_worker_id": "worker-1",
      "solver_latency_ms": 3.42,
      "status": "DISPATCHED"
    }
  ],
  "queue_depth": 0
}
```

---

## 3. Team Member Modules, Responsibilities & AI Prompts

---

### MEMBER 1: ANANYA
**Official Role:** Monitoring & Data Collection Engineer  
**Scope of Work:**
* **Module:** Worker Infrastructure, Host Monitoring & Telemetry Caching
* **Technologies:** Python 3.10+, `psutil`, `httpx`, Redis, GCP Compute Engine Ubuntu instances, systemd

#### What Ananya Manages:
1. **GCP Ubuntu Worker VMs:** Sets up `cb-worker-1` and `cb-worker-2` on Google Cloud Compute Engine, ensuring network reachability and system packages.
2. **psutil Telemetry Daemon (`worker_agent/agent.py`):**
   * Writes a daemon loop that samples real hardware usage: CPU usage (`psutil.cpu_percent(interval=None)`), Memory usage (`psutil.virtual_memory()`), and Load average (`psutil.getloadavg()`).
   * Packages this telemetry into the standard JSON contract with a timestamp and worker ID.
   * Sends the telemetry via HTTP POST to FastAPI every 2.0 seconds.
3. **Redis Real-Time Snapshot Store:**
   * Works with Member 3 so that incoming telemetry is written to Redis under the key `cluster:worker:{worker_id}`.
   * Enforces a 10-second Time-To-Live (TTL) on Redis keys to ensure dead or disconnected VMs automatically drop out of the cluster state.
4. **Worker Execution Daemon (`worker_agent/executor.py`):**
   * Sets up a lightweight FastAPI/Uvicorn HTTP server on port `8001` on each worker VM.
   * Listens for `POST /execute` commands containing `{task_id, duration_sec, matrix_dim}` and runs the NumPy FLOP workload so that `psutil` reads real physical utilization.

#### Professional AI Prompt for Member 1 (Ananya):
```text
You are an expert Systems and Cloud Infrastructure Engineer working on the CloudBalance project. Your assigned role is Member 1 (Ananya) – Monitoring & Data Collection.

PROJECT CONTEXT:
CloudBalance is a distributed cloud load balancer running on GCP Compute Engine Ubuntu VMs. It balances multi-resource workloads using Google OR-Tools. You are the sensing layer of the entire system: if your monitoring data is inaccurate or delayed, the optimizer will make flawed load-balancing decisions.

YOUR DELIVERABLES:
1. File: `worker_agent/agent.py`
   - Use Python's `psutil` and `httpx` to continuously sample node health every 2.0 seconds.
   - Collect: `worker_id`, `ip_address`, `timestamp`, `cpu_percent`, `memory_total_mb`, `memory_used_mb`, `memory_percent`, `load_avg_1m`, and `active_task_count`.
   - Send HTTP POST requests to the FastAPI Controller at `http://<CONTROLLER_INTERNAL_IP>:8000/api/telemetry`.
   - Implement robust error handling (auto-retry with exponential backoff if Controller is temporarily unavailable).
   - Package the script with a systemd service definition (`cloudbalance-agent.service`) to run continuously in the background on Ubuntu.

2. File: `worker_agent/executor.py`
   - A lightweight FastAPI server running on port 8001 on each worker VM.
   - Endpoint: `POST /execute` accepting JSON: `{"task_id": str, "matrix_dim": int, "duration_sec": float}`.
   - Executes NumPy BLAS matrix multiplication (`numpy.dot`) on a float32 array of size (matrix_dim, matrix_dim) continuously in a separate thread until `duration_sec` has elapsed.
   - Increments and decrements `active_task_count` accurately so `agent.py` reads current concurrent task counts.

3. Redis Telemetry Strategy:
   - Provide the exact Redis caching logic used by the backend: store data at key `cluster:worker:{worker_id}` with a 10-second TTL (`SETEX cluster:worker:{worker_id} 10 <json_payload>`).
   - Explain how this TTL mechanism provides automated dead-node detection and fault tolerance for the cluster.

Write clean, production-grade, well-commented Python code. Ensure non-blocking async execution where appropriate.
```

---

### MEMBER 2: SUMEDH
**Official Role:** Workload Modeling & Mathematical Optimization Engineer  
**Scope of Work:**
* **Module:** Job Traffic Generation & Google OR-Tools Optimization Engine
* **Technologies:** Python, NumPy, SciPy, Google OR-Tools (MILP / CBC solver), `httpx`, Asyncio

#### What Sumedh Manages:
1. **Poisson Traffic Arrival Process (`optimizer/traffic_generator/poisson_generator.py`):**
   * Implements a realistic arrival model using inverse transform sampling of the Exponential Distribution:
     $$dt = -\frac{\ln(1 - U)}{\lambda}$$
     where $U \sim \text{Uniform}(0, 1)$ and $\lambda$ is the arrival rate (tasks/second).
   * Creates real-world burstiness: variable idle pauses followed by sudden request clusters.
2. **Multi-Resource Workload Profiling (`optimizer/traffic_generator/workloads.py`):**
   * Formulates distinct task archetypes (CPU-Intensive, Memory-Intensive, Balanced, and Lightweight Query).
   * Couples each task with concrete execution parameters (`matrix_dim` and `duration_sec`) to guarantee physical FLOPs on worker nodes.
3. **Google OR-Tools MILP Solver (`optimizer/solver/ortools_optimizer.py`):**
   * Formulates the assignment problem mathematically:
     - Binary decision variable $X_{ij} \in \{0, 1\}$ ($1$ if Task $i$ is assigned to Worker $j$).
     - Single assignment constraint: $\sum_{j=1}^M X_{ij} = 1 \quad \forall i$.
     - CPU capacity constraint: $\text{Current\_CPU}_j + \sum_{i=1}^N (X_{ij} \times \text{Req\_CPU}_i) \le \text{Max\_CPU}_j$ (default 85%).
     - RAM capacity constraint: $\text{Current\_Mem}_j + \sum_{i=1}^N (X_{ij} \times \text{Req\_Mem}_i) \le \text{Max\_Mem}_j \times 0.90$.
     - Min-Max Objective: $\min Z$ subject to $\text{Projected\_CPU}_j \le Z \quad \forall j$.
   * Ensures sub-10ms solving latency per batch.
   * Implements fallback heuristics in case of constraint oversubscription.
4. **Real-Time Client CLI Runner (`optimizer/simulate_traffic.py`):**
   * Supports **Local Test Mode** (mock workers for instant local validation without GCP fees).
   * Supports **Live Cloud Mode** (fires real HTTP requests across the internet to the GCP Controller).

#### Professional AI Prompt for Member 2 (Sumedh):
```text
You are an expert Operations Research and Mathematical Modeling Engineer working on the CloudBalance project. Your assigned role is Member 2 (Sumedh) – Workload Modeling & Mathematical Optimization.

PROJECT CONTEXT:
CloudBalance replaces naive heuristic load balancing (Round-Robin, Least-Connections) with an adaptive, multi-resource mathematical optimizer using Google OR-Tools. You are responsible for modeling realistic user traffic using a Poisson process and solving the multi-dimensional server assignment problem in real time.

YOUR DELIVERABLES:
1. File: `optimizer/traffic_generator/workloads.py`
   - Define concrete workload archetypes: CPU_INTENSIVE (high matrix FLOPs, low RAM), MEMORY_INTENSIVE (large matrix dimension buffers, moderate CPU), BALANCED_COMPUTE, and LIGHTWEIGHT_QUERY.
   - Implement `create_task_payload()` generating task dicts with {task_id, type, cpu_demand_pct, mem_demand_mb, duration_sec, matrix_dim, created_at}.
   - Implement `execute_physical_workload(matrix_dim, duration_sec)` using `numpy.dot` on float32 arrays to pin vCPU cores and allocate RAM buffers.

2. File: `optimizer/traffic_generator/poisson_generator.py`
   - Implement `PoissonTrafficGenerator` using the exponential inter-arrival formula `dt = -math.log(1.0 - u) / arrival_rate_lambda`.
   - Provide an async generator `stream_tasks()` that yields tasks separated by genuine `await asyncio.sleep(dt)` intervals in real time.
   - Allow dynamic modification of lambda on the fly to simulate traffic spikes and quiet valleys.

3. File: `optimizer/solver/ortools_optimizer.py`
   - Implement `solve_task_assignment(pending_tasks, workers, max_cpu_limit=85.0)`.
   - Use Google OR-Tools CBC/SCIP linear solver (`pywraplp.Solver.CreateSolver('CBC')`).
   - Define binary decision variables X_ij in {0, 1}.
   - Add single-assignment constraint (each task assigned to exactly one worker).
   - Add multi-resource constraints (projected CPU <= 85%, projected RAM <= 90% total capacity).
   - Formulate Min-Max load balancing: minimize auxiliary variable Z subject to Projected_CPU_j <= Z.
   - Return task-to-worker assignments and metadata (solve latency in ms, solver status, projected peak load).
   - Include a graceful fallback heuristic if the solver finds the batch infeasible due to extreme saturation.

4. File: `optimizer/simulate_traffic.py`
   - Build a CLI runner supporting `--target-url`, `--lambda`, and `--max-tasks`.
   - If `--target-url` is passed, send live HTTP POST requests using `httpx.AsyncClient` to the GCP Controller VM over the public internet.
   - If omitted, run a local demo simulation with mock workers and live console logs of task assignments and cluster CPU evolution.

Write mathematically rigorous, highly efficient Python code with full type hints and docstrings.
```

---

### MEMBER 3: NAFISA
**Official Role:** Backend, Dispatch & Communications Engineer  
**Scope of Work:**
* **Module:** Central FastAPI Backend, Worker Dispatcher, WebSocket Server & MongoDB Auditing
* **Technologies:** Python, FastAPI, Uvicorn, Redis (`redis-py`), MongoDB Atlas (`pymongo` / `motor`), WebSockets, Pydantic

#### What Nafisa Manages:
1. **Central FastAPI Application (`backend/app/main.py`):**
   * Acts as the single coordinator hosted on `cloudbalance-controller` (port `8000`).
   * Configures CORS and handles routing across API endpoints.
2. **API Endpoints:**
   * `POST /api/telemetry`: Validates incoming data from Member 1's agents via Pydantic and caches it in Redis (`SETEX cluster:worker:{id} 10 <json>`).
   * `POST /api/tasks`: Receives tasks from Member 2's traffic generator, reads active worker states from Redis, passes both into Member 2's OR-Tools solver, and dispatches the assignments.
   * `POST /api/dispatch`: Dispatches tasks directly to the assigned worker's HTTP endpoint (`http://<worker_ip>:8001/execute`).
3. **Real-Time WebSocket Server (`backend/app/api/websocket.py`):**
   * Maintains persistent WebSocket connections with Member 4's React UI (`ws://<host>:8000/ws/live`).
   * Periodically gathers live cluster snapshots and broadcasts updates every 1.5 seconds.
4. **Historical Database & Auditing (`MongoDB Atlas`):**
   * Persists completed task records, actual vs. predicted execution times, solver latency history, and comparative baseline runs for viva evaluation.

#### Professional AI Prompt for Member 3 (Nafisa):
```text
You are an expert Backend and Distributed Systems Engineer working on the CloudBalance project. Your assigned role is Member 3 (Nafisa) – Backend, Dispatch & Communications.

PROJECT CONTEXT:
CloudBalance is a distributed cloud load balancer. You build the central nervous system hosted on the GCP `cloudbalance-controller` VM. You connect Member 1's monitoring telemetry (stored in Redis), invoke Member 2's Google OR-Tools optimization engine, dispatch execution jobs to worker VMs, log historical data in MongoDB, and broadcast live state to Member 4's React dashboard via WebSockets.

YOUR DELIVERABLES:
1. File: `backend/app/main.py` & Directory Architecture
   - Set up FastAPI with CORS middleware and clean modular routing (`/api/telemetry`, `/api/tasks`, `/api/dispatch`, `/ws/live`).
   - Define strict Pydantic models for `TelemetryPayload`, `TaskPayload`, and `AssignmentResponse`.

2. File: `backend/app/api/telemetry.py`
   - Endpoint: `POST /api/telemetry`.
   - Ingests worker telemetry, validates schema, and writes directly into Redis:
     `SETEX cluster:worker:{worker_id} 10 <json_payload>`.
   - Returns 200 OK.

3. File: `backend/app/api/tasks.py` & `backend/app/services/dispatcher.py`
   - Endpoint: `POST /api/tasks`.
   - Receives tasks from Member 2's generator.
   - Reads all active worker keys from Redis (`KEYS cluster:worker:*` or hash).
   - If no active workers are found in Redis, returns 503 Service Unavailable.
   - Invokes Member 2's optimizer: `assignments, meta = solve_task_assignment([task], active_workers)`.
   - Asynchronously dispatches the task to the selected worker: `POST http://<worker_ip>:8001/execute`.
   - Logs task details and solver latency to MongoDB (`tasks_history` collection).
   - Returns assignment status to the caller.

4. File: `backend/app/api/websocket.py`
   - WebSocket endpoint at `/ws/live`.
   - Maintains an active connection manager for connected frontend clients.
   - Gathers live snapshots of all active workers from Redis and recent task assignments, broadcasting a structured JSON message (`event_type: "CLUSTER_SNAPSHOT"`) every 1.5 seconds.

5. MongoDB Integration (`backend/app/core/mongo_client.py`):
   - Connects to MongoDB Atlas using `motor` or `pymongo`.
   - Persists task lifecycle events: `task_id`, `assigned_worker`, `solver_latency_ms`, `cpu_projected`, and timestamp.

Write modular, asynchronous, production-ready Python code with proper exception handling and clean architecture.
```

---

### MEMBER 4: SHUBHAM
**Official Role:** Dashboard & Visualization Frontend Engineer  
**Scope of Work:**
* **Module:** Real-Time Cloud Monitoring Dashboard & Traffic Control Interface
* **Technologies:** React 18+ (Vite), Tailwind CSS, Chart.js / `react-chartjs-2`, WebSockets

#### What Shubham Manages:
1. **React Application Architecture (`frontend/src/`):**
   * Initializes a high-performance single-page application using Vite and Tailwind CSS.
   * Manages global live state populated entirely by WebSocket messages from FastAPI.
2. **Live WebSocket Hook (`frontend/src/hooks/useWebSocket.js`):**
   * Connects to `ws://<CONTROLLER_IP>:8000/ws/live`.
   * Implements auto-reconnect logic with exponential backoff if the network disconnects.
3. **Server Health Cards (`WorkerCard.jsx`):**
   * Displays one card per active GCP worker VM.
   * Dynamic color-coded status badges:
     - **Green (Healthy):** CPU $< 60\%$ and RAM $< 70\%$
     - **Yellow (Moderate):** CPU $60\% - 84\%$ or RAM $70\% - 89\%$
     - **Red (Heavy / Critical):** CPU $\ge 85\%$ or RAM $\ge 90\%$
   * Shows active task count, CPU usage gauge/bar, and used vs. total memory (MB).
4. **Time-Series Resource Charts (`MetricsChart.jsx`):**
   * Uses Chart.js to display the last 30 data points of CPU and RAM utilization for all workers side-by-side.
   * Allows evaluators to visually verify how the OR-Tools optimizer balances workloads evenly across nodes over time.
5. **Live Assignment Feed (`TaskQueue.jsx`):**
   * Displays incoming tasks, their resource demands, and the assigned worker VM in real time.

#### Professional AI Prompt for Member 4 (Shubham):
```text
You are an expert Frontend and Data Visualization Engineer working on the CloudBalance project. Your assigned role is Member 4 (Shubham) – Dashboard & Visualization.

PROJECT CONTEXT:
CloudBalance is a distributed cloud load balancer running on GCP. The system takes multi-resource computational tasks and balances them across Ubuntu VMs using Google OR-Tools. You build the user-facing command center: a real-time web dashboard that visually proves to evaluators and professors that the system is dynamically sensing worker loads and balancing traffic.

YOUR DELIVERABLES:
1. Project Setup: React + Vite + Tailwind CSS
   - Initialize Vite React app with Tailwind CSS configuration.
   - Clean, dark-mode modern cloud operations center UI theme (slate/zinc background with emerald/amber/rose status accents).

2. File: `src/hooks/useWebSocket.js`
   - Connects to `ws://<BACKEND_HOST>:8000/ws/live`.
   - Listens for `CLUSTER_SNAPSHOT` events.
   - Maintains connection state (`connected`, `disconnected`, `reconnecting`).
   - Automatically reconnects if the socket drops.

3. File: `src/components/WorkerCard.jsx`
   - Renders individual cards for each active worker VM.
   - Shows: Worker ID, IP address, CPU % bar, RAM % and used/total MB, and active task count.
   - Dynamic threshold indicators:
     * Green border/pill: CPU < 60% (Available / Healthy)
     * Yellow border/pill: CPU 60%–84% (Moderate Load)
     * Red border/pill: CPU >= 85% (Overload / Critical)

4. File: `src/components/MetricsChart.jsx`
   - Uses Chart.js (`react-chartjs-2`) to render live rolling time-series charts of CPU and RAM utilization across all workers.
   - Shows multiple colored lines (one line per worker node) updating smoothly as new WebSocket messages arrive.
   - Preserves the last 30 data points for continuous timeline review.

5. File: `src/components/TaskQueue.jsx`
   - Real-time ticker/table showing the last 10 assigned tasks: Task ID, Workload Type (CPU vs RAM), CPU Demand %, Assigned Worker, Solver Latency (ms), and Status badge.

Write modular, clean, responsive React components with modern Tailwind CSS styling. Ensure components do not lag during frequent WebSocket updates.
```

---

## 4. Master GCP Cloud Provisioning & Deployment Runbook

### 4.1. GCP Cloud Shell Provisioning Script
Run these exact commands in Google Cloud Shell to instantiate the entire infrastructure:

```bash
# 1. Create dedicated VPC network
gcloud compute networks create cloudbalance-net --subnet-mode=auto

# 2. Allow SSH access
gcloud compute firewall-rules create allow-cloudbalance-ssh \
    --network=cloudbalance-net \
    --allow=tcp:22 \
    --source-ranges=0.0.0.0/0 \
    --description="SSH access"

# 3. Allow Public Web Traffic (Dashboard on 3000, Backend on 8000)
gcloud compute firewall-rules create allow-cloudbalance-public \
    --network=cloudbalance-net \
    --allow=tcp:8000,tcp:3000 \
    --source-ranges=0.0.0.0/0 \
    --description="Public UI and API access"

# 4. Allow Internal VPC Traffic (Worker execution on 8001, Redis on 6379, Internal API on 8000)
gcloud compute firewall-rules create allow-cloudbalance-internal \
    --network=cloudbalance-net \
    --allow=tcp:6379,tcp:8000,tcp:8001,icmp \
    --source-ranges=10.128.0.0/9 \
    --description="Internal cluster communication"

# 5. Provision Controller VM (Host for Backend, Redis, UI)
gcloud compute instances create cloudbalance-controller \
    --zone=us-central1-a \
    --machine-type=e2-standard-2 \
    --network=cloudbalance-net \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --tags=controller-node

# 6. Provision Worker VM 1
gcloud compute instances create cb-worker-1 \
    --zone=us-central1-a \
    --machine-type=e2-medium \
    --network=cloudbalance-net \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --tags=worker-node

# 7. Provision Worker VM 2
gcloud compute instances create cb-worker-2 \
    --zone=us-central1-a \
    --machine-type=e2-medium \
    --network=cloudbalance-net \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --tags=worker-node
```

### 4.2. Worker Deployment Commands (Member 1 on `cb-worker-1` and `cb-worker-2`)
```bash
gcloud compute ssh cb-worker-1 --zone=us-central1-a

# Install packages
sudo apt update && sudo apt install -y python3-pip python3-venv git
python3 -m venv venv && source venv/bin/activate
pip install psutil httpx uvicorn fastapi numpy

# Run worker execution server on port 8001
nohup uvicorn executor:app --host 0.0.0.0 --port 8001 > executor.log 2>&1 &

# Run psutil agent reporting to controller internal IP (10.128.0.10)
nohup python3 agent.py --worker-id worker-1 --backend-url http://10.128.0.10:8000 > agent.log 2>&1 &
```

### 4.3. Controller Deployment Commands (Member 3 & 4 on `cloudbalance-controller`)
```bash
gcloud compute ssh cloudbalance-controller --zone=us-central1-a

# Install Redis, Node.js, and Python
sudo apt update && sudo apt install -y redis-server python3-pip python3-venv git nodejs npm
sudo systemctl enable redis-server && sudo systemctl start redis-server

# Run FastAPI Backend with OR-Tools
cd CloudBalance/backend
python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn redis pymongo ortools numpy httpx pydantic
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1 &

# Build and Serve React Dashboard
cd ../frontend
npm install
npm run build
nohup npx serve -s dist -l 3000 > frontend.log 2>&1 &
```

### 4.4. Traffic Execution Commands (Member 2 on Client PC)
```bash
# Run real-time Poisson traffic generator against the GCP Controller external IP
python optimizer/simulate_traffic.py --target-url http://<CONTROLLER_EXTERNAL_IP>:8000 --lambda 1.5 --max-tasks 50
```

---

## 5. Viva Evaluation & Demonstration Protocol

When demonstrating CloudBalance to evaluators:

1. **Phase 1: Cluster Idle Baseline**
   * Open the React Dashboard (`http://<CONTROLLER_EXTERNAL_IP>:3000`).
   * Show that all worker cards are **Green (Healthy)** with CPU ~2% and RAM ~15%.
   * Point out that Redis is actively refreshed with `psutil` telemetry every 2 seconds.

2. **Phase 2: Poisson Workload Injection**
   * Member 2 launches `simulate_traffic.py` on the client laptop.
   * Highlight the inter-arrival gaps $dt$: explain that tasks arrive with mathematical burstiness, matching real web user behavior.
   * Tasks arrive at FastAPI, triggering Google OR-Tools.

3. **Phase 3: The Closed Feedback Loop in Action**
   * OR-Tools maps Task 1 to `Worker 1`.
   * Worker 1's executor runs physical NumPy matrix multiplications.
   * Member 1's `psutil` agent detects CPU rising to ~65% (Card turns **Yellow** on the Dashboard).
   * When Task 2 arrives, explain that OR-Tools **reads the fresh Redis snapshot**, recognizes Worker 1 is busy, and dynamically steers Task 2 to `Worker 2`.

4. **Phase 4: High-Burst Stress Test**
   * Increase Poisson $\lambda$ to 5.0 (`--lambda 5.0`).
   * Show that OR-Tools strictly enforces the 85% CPU and 90% RAM constraints, queuing or distributing tasks without causing Out-of-Memory (OOM) crashes.
   * Contrast this with **Round-Robin**, which would blindly dump tasks onto already-stressed nodes and crash the VM.

