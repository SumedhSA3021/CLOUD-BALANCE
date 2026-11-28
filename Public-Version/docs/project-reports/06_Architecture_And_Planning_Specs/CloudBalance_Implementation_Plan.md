# CloudBalance: System Implementation Plan

## 1. Executive Summary & Architecture Overview

**CloudBalance** is an adaptive, resource-aware cloud load-balancing platform designed to distribute computational workloads across Google Cloud Compute Engine Ubuntu VMs. Rather than relying on naive single-metric heuristics (e.g., Round Robin or Least Connections), CloudBalance uses a mathematical Mixed-Integer Linear Programming (MILP) model solved with **Google OR-Tools** to balance CPU and Memory across worker nodes in real time.

```
       +--------------------------------------------------------+
       |   [Member 2] Traffic Generator (Poisson + NumPy)        |
       +--------------------------------------------------------+
                                  |
                                  | 1. Generates Task {id, cpu_req, mem_req, duration}
                                  v
+-------------------------------------------------------------------------------+
|                        [Member 3] FastAPI Central Backend                     |
|                                                                               |
|  +------------------+    2. Solves     +-----------------------------------+  |
|  | Task Queue /     | ---------------> | [Member 2] Optimization Engine    |  |
|  | Ingestion Buffer | <--------------- | (Google OR-Tools MILP Solver)     |  |
|  +------------------+     Assignment   +-----------------------------------+  |
|           |                                       ^                           |
|           | 3. Reads server health snapshot       | Reads live VM metrics     |
|           v                                       |                           |
|     [(Redis Cache)] <-----------------------------+                           |
|           ^                                                                   |
|           | Updates telemetry every 2-3s                                      |
|           |                                                                   |
|  +------------------+                          +---------------------------+  |
|  | Historical Data  |                          | WebSocket Broadcaster     |  |
|  | Store (MongoDB)  |                          | (Push updates to frontend)|  |
|  +------------------+                          +---------------------------+  |
+--------------------------------------------------------------|----------------+
         |                                                     |
         | 4. Dispatches Task                                  | 5. Real-time stream
         v                                                     v
+------------------------------------+          +-------------------------------+
| [Member 1] GCP Ubuntu Worker VMs   |          | [Member 4] Frontend Dashboard |
| (Worker 1, Worker 2, Worker N)     |          | (React + Tailwind + Chart.js) |
| - Worker runner executes NumPy FLOPs|         | - Real-time CPU/RAM gauges    |
| - psutil Monitoring Agent runs loop |         | - Active VM status cards      |
|   and pushes to FastAPI /telemetry  |         | - Live assignment feed & queue|
+------------------------------------+          +-------------------------------+
```

---

## 2. Team Member Division & Responsibilities

| Member | Assigned Area | Technologies | Core Responsibilities |
| :--- | :--- | :--- | :--- |
| **Member 1 (Ananya)** | **Monitoring & Data Collection** | Python, `psutil`, `requests`/`httpx`, Redis, GCP Compute Engine | • Set up GCP Ubuntu VMs.<br>• Implement lightweight daemon agent collecting CPU %, RAM (used/total), load avg, and active task count.<br>• Transmit telemetry every 2–3s to FastAPI.<br>• Maintain live node state in Redis (`SET worker:{id} {metrics} EX 10`). |
| **Member 2 (M2)** | **Job Traffic Generation & Optimization Engine** | Python, NumPy, SciPy, Google OR-Tools (MILP/SCIP/CBC) | • Generate synthetic workloads with Poisson inter-arrival intervals ($dt = -\ln(1-U)/\lambda$).<br>• Define resource contracts (CPU %, RAM MB, NumPy FLOP workload matrix dimensions).<br>• Formulate and solve the MILP optimization model (fairness/min-max peak utilization, capacity limits, single-assignment). |
| **Member 3 (Nafisa)** | **Backend, Dispatch & Communication** | Python, FastAPI, WebSockets, MongoDB, `motor` / `pymongo` | • Core FastAPI REST API endpoints (`/telemetry`, `/tasks`, `/dispatch`).<br>• Connect Redis snapshot lookups with OR-Tools engine invocation.<br>• Dispatch task payloads to target worker VM endpoints.<br>• Log task lifecycle & performance metrics into MongoDB.<br>• Broadcast real-time cluster events to UI over WebSockets. |
| **Member 4 (Remaining Teammate)** | **Dashboard & Visualization** | React (Vite), Tailwind CSS, Chart.js / Recharts, WebSockets | • Live cluster overview: server health cards (CPU/Memory gauges).<br>• Real-time time-series charts for node load evolution.<br>• Live task queue & assignment visualizer.<br>• Stress simulation control panel (trigger Poisson burst, change $\lambda$, pause/resume). |

---

## 3. Data Contracts & API Specifications

### 3.1. Telemetry Payload (`Worker Agent -> Backend`)
**Endpoint:** `POST /api/telemetry`
```json
{
  "worker_id": "worker-1",
  "ip_address": "10.128.0.2",
  "timestamp": 1772966400.12,
  "cpu_percent": 34.5,
  "memory_total_mb": 4096,
  "memory_used_mb": 1420,
  "memory_percent": 34.6,
  "load_avg_1m": 0.45,
  "active_task_count": 2
}
```
*Backend action:* Writes to Redis with TTL: `SETEX cluster:worker:worker-1 10 '{"cpu": 34.5, ...}'`.

### 3.2. Task Definition (`Generator -> Backend Queue`)
**Endpoint:** `POST /api/tasks`
```json
{
  "task_id": "task-7b3d91",
  "cpu_demand_pct": 25.0,
  "mem_demand_mb": 512,
  "duration_sec": 4.5,
  "matrix_dim": 2200,
  "created_at": 1772966405.01
}
```

### 3.3. Optimization Input / Output
* **Solver Input:**
  * Pending tasks: `[Task_1, Task_2, ... Task_N]`
  * Active servers: `[Worker_1, Worker_2, ... Worker_M]` with current CPU % and RAM MB.
* **Solver Constraints:**
  1. $\sum_{j=1}^M X_{ij} = 1 \quad \forall i$ (Single assignment)
  2. $\text{Current\_CPU}_j + \sum_{i=1}^N (X_{ij} \times \text{Req\_CPU}_i) \le \text{Max\_CPU}_j$ (CPU safety threshold, e.g., 85%)
  3. $\text{Current\_Mem}_j + \sum_{i=1}^N (X_{ij} \times \text{Req\_Mem}_i) \le \text{Max\_Mem}_j$ (Memory OOM prevention)
* **Objective:** Minimize peak server load $\min Z$ subject to $\text{Load}_j \le Z$ (Min-Max load balance).
* **Output:** `X[i][j]` mapping:
```json
{
  "assignments": [
    {"task_id": "task-7b3d91", "assigned_worker_id": "worker-2"}
  ],
  "solver_latency_ms": 3.4
}
```

### 3.4. Task Dispatch & Execution (`Backend -> Worker VM`)
**Worker Endpoint:** `POST http://<worker_ip>:8001/execute`
* The VM receives payload and spawns a thread/process running real NumPy matrix multiplications to create measurable FLOPs and RAM allocation for the specified duration.

### 3.5. Real-Time WebSocket Feed (`Backend -> Frontend Dashboard`)
**WebSocket:** `ws://<backend_host>:8000/ws/live`
```json
{
  "type": "CLUSTER_UPDATE",
  "timestamp": 1772966405.5,
  "workers": [
    {"id": "worker-1", "cpu": 34.5, "mem": 34.6, "status": "HEALTHY", "active_tasks": 2},
    {"id": "worker-2", "cpu": 65.0, "mem": 52.1, "status": "BUSY", "active_tasks": 4}
  ],
  "recent_assignments": [
    {"task_id": "task-7b3d91", "worker_id": "worker-2", "status": "DISPATCHED"}
  ],
  "queue_depth": 0
}
```

---

## 4. Suggested Project Directory Structure

```text
CloudBalance/
│
├── backend/                        # Member 3 (FastAPI, Redis, Mongo, Dispatcher)
│   ├── app/
│   │   ├── api/
│   │   │   ├── telemetry.py        # Ingests agent telemetry -> Redis
│   │   │   ├── tasks.py            # Receives tasks, triggers optimization
│   │   │   └── websocket.py        # Pushes live cluster state to Member 4 UI
│   │   ├── core/
│   │   │   ├── config.py           # Env variables (Redis URL, Mongo URI)
│   │   │   ├── redis_client.py     # Redis connection & cache helpers
│   │   │   └── mongo_client.py     # MongoDB database models & motor client
│   │   ├── services/
│   │   │   ├── dispatcher.py       # Calls worker VM /execute endpoints
│   │   │   └── optimizer_bridge.py # Interfaces with Member 2's OR-Tools module
│   │   └── main.py                 # FastAPI application entrypoint
│   ├── requirements.txt
│   └── run_backend.py
│
├── optimizer/                      # Member 2 (Traffic Generation & OR-Tools Solver)
│   ├── traffic_generator/
│   │   ├── poisson_generator.py    # Poisson inter-arrival process & task builder
│   │   └── workloads.py            # Matrix size vs CPU/RAM profiles
│   ├── solver/
│   │   ├── ortools_optimizer.py    # MILP model (Google OR-Tools)
│   │   └── baseline_heuristics.py  # Round-Robin & Least-Conn (for comparison tests)
│   └── simulate_traffic.py         # Standalone traffic runner script
│
├── worker_agent/                   # Member 1 (Runs on each GCP Ubuntu Worker VM)
│   ├── agent.py                    # psutil continuous loop -> posts to backend
│   ├── executor.py                 # Lightweight HTTP server executing NumPy FLOPs
│   ├── requirements.txt            # psutil, requests, numpy, uvicorn, fastapi
│   └── setup_vm.sh                 # Cloud-init / shell script to provision Ubuntu VM
│
└── frontend/                       # Member 4 (React + Tailwind + Chart.js Dashboard)
    ├── src/
    │   ├── components/
    │   │   ├── WorkerCard.jsx      # Per-node CPU/RAM gauge & task counter
    │   │   ├── MetricsChart.jsx    # Real-time resource history line chart
    │   │   ├── TaskQueue.jsx       # Real-time assignment ticker & queue depth
    │   │   └── ControlPanel.jsx    # Traffic generation triggers (Poisson Lambda slider)
    │   ├── hooks/
    │   │   └── useWebSocket.js     # Manages auto-reconnecting WS connection
    │   ├── App.jsx
    │   └── main.jsx
    ├── package.json
    └── tailwind.config.js
```

---

## 5. Phased Step-by-Step Implementation Roadmap

### Phase 1: Environment Setup & Core Foundations (Week 1)
- **Member 1:** Provision 2–3 Google Cloud Compute Engine e2-medium/standard Ubuntu instances. Ensure firewall allows traffic on ports 8000/8001. Write initial `agent.py` using `psutil`.
- **Member 3:** Initialize FastAPI backend skeleton. Configure local/cloud Redis and MongoDB Atlas instances. Verify connectivity.
- **Member 2:** Write `poisson_generator.py` and test exponential inter-arrival distribution. Build the matrix computation function in `executor.py` that reliably drives measurable CPU and memory.
- **Member 4:** Set up Vite React project with Tailwind CSS and Chart.js/Recharts. Create mock UI components with dummy node data.

### Phase 2: Inter-Module Wiring & Core Logic (Week 2)
- **Member 1 & 3 Integration:** Member 1's agent begins streaming metrics to FastAPI `POST /api/telemetry`; Member 3 validates payloads with Pydantic and caches in Redis.
- **Member 2:** Build `ortools_optimizer.py` using Google OR-Tools. Implement MILP decision variable $X_{ij}$, CPU/RAM limits, and Min-Max fairness objective. Benchmark solve time (< 10ms).
- **Member 3 & 2 Integration:** FastAPI retrieves current node snapshots from Redis, passes them into OR-Tools along with pending tasks, and receives assignment targets.
- **Member 3 & 4 Integration:** Establish WebSocket endpoint `/ws/live`. Push live Redis cluster snapshots to Member 4's React UI every 1–2 seconds.

### Phase 3: Closed-Loop Dispatch & Realistic Workload Execution (Week 3)
- **Worker Execution:** Implement `worker_agent/executor.py` on worker VMs. When FastAPI receives assignments from OR-Tools, it calls `POST http://<vm_ip>:8001/execute`.
- **Dynamic Feedback Loop:** As NumPy executes on VM, Member 1's `psutil` agent detects CPU/RAM spikes, posts to FastAPI, updates Redis, and Member 2's next OR-Tools cycle adapts by steering traffic away from stressed VMs.
- **Member 3:** Record all completed tasks, response times, and solver latencies in MongoDB for viva analysis and comparison.
- **Member 4:** Connect live WebSocket stream to update real-time charts and visual indicators (Green/Orange/Red server load states).

### Phase 4: Comparative Benchmarking & Viva Defense (Week 4)
- **Algorithm Comparison:** Run identical Poisson traffic streams against:
  1. Naive Round Robin
  2. Least Connections
  3. **CloudBalance OR-Tools Adaptive Optimization**
- **Metrics Collection:** Compare standard deviation of cluster CPU/Memory, peak latency, and OOM crash count.
- **Frontend Polish:** Display comparative performance metrics and graphs on the dashboard.
- **Viva Drill:** Practice full system demo: starting Poisson bursts, watching real-time OR-Tools balancing, and presenting the slides.
