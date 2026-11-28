# CloudBalance: Local Machine Execution Implementation Plan

## 1. Executive Summary & Objective

**CloudBalance** was originally designed to run across multiple Google Cloud Platform (GCP) Compute Engine VMs (1 Controller + 2 Worker nodes). This implementation plan defines the complete engineering blueprint to adapt and execute the **entire distributed system on a single local machine (Windows)** without requiring active cloud subscriptions, external VMs, or complex Docker configurations.

### Key Local Architecture Innovations
1. **Multi-Process Worker Virtualization:** Run multiple worker nodes (`worker-1` on port `8001`, `worker-2` on port `8002`, `worker-3` on port `8003`) as independent local background processes.
2. **Process-Sliced Telemetry:** Each local worker agent simulates independent virtualized CPU/RAM load profiles while executing genuine physical NumPy BLAS matrix operations, ensuring distinct, realistic metric variations on a single computer.
3. **Zero-Dependency Resilience:** Dual-mode storage engine:
   - Uses real Redis and MongoDB if locally installed/configured.
   - Automatically falls back to a transparent, high-performance in-memory key-value cache with TTL expiration and local SQLite/JSON audit logging if Redis/MongoDB are absent.
4. **Interactive Command Center:** A modern React + Vite + Tailwind CSS dark-mode operations dashboard communicating over WebSockets (`ws://localhost:8000/ws/live`), with live charts, worker status cards, and an interactive simulation control panel.
5. **One-Click Orchestration (`launch_local.py`):** A unified process launcher that boots the Controller, Workers, Frontend, and Traffic Generator in coordinated sequence with graceful shutdown handling.

---

## 2. Local Architecture Blueprint

```
[Member 2: Traffic Generator (CLI / UI)]
  • Poisson Traffic Streamer: dt = -ln(1-U) / lambda
  • Workload Profiles: CPU-bound (FLOPs), RAM-bound (Buffers), Balanced
             │
             │ POST /api/tasks
             ▼
==================================================================================
   LOCAL CENTRAL CONTROLLER (Port 8000)
==================================================================================
  ┌─────────────────────────────────┐      ┌───────────────────────────────────┐
  │ FastAPI Central Backend         │ ◄─── │ Redis / In-Memory Cache           │
  │ • /api/telemetry (Ingests agent)│      │ • Key: cluster:worker:{id}        │
  │ • /api/tasks (Buffers & solves) │      │ • 10-second TTL auto-eviction     │
  │ • /ws/live (WebSocket stream)   │      │ • Zero-external-dependency fallback│
  └───────────────┬─────────────────┘      └─────────────────▲─────────────────┘
                  │                                          │
                  │ Solves optimal batch assignment          │ Reads active node
                  ▼                                          │ health metrics
  ┌─────────────────────────────────┐                        │
  │ Google OR-Tools MILP Solver     │────────────────────────┘
  │ • Min-Max Peak Utilization (min Z)
  │ • CPU <= 85%, RAM <= 90% caps
  └───────────────┬─────────────────┘
                  │
        ┌─────────┴─────────┐
        │ Internal Dispatch │
        │ POST :800X/execute│
        ▼                   ▼
┌──────────────────┐    ┌──────────────────┐
│ Worker 1 (:8001) │    │ Worker 2 (:8002) │
│ • psutil Agent   │    │ • psutil Agent   │
│ • NumPy Executor │    │ • NumPy Executor │
└──────────────────┘    └──────────────────┘
        ▲                         ▲
        │                         │
WebSocket Snapshot Broadcasts (/ws/live)
        ▼
┌──────────────────────────────────────────┐
│ Member 4: Operations Dashboard (Port 3000/5173)
│ • Live CPU & RAM Gauges, Health Pills    │
│ • Chart.js Time-Series Load Evolution    │
│ • Interactive Traffic Controller         │
│ • OR-Tools vs. Round-Robin Comparison    │
└──────────────────────────────────────────┘
```

---

## 3. Implementation Phases & Milestones

### Phase 1: Environment & Dependency Setup
* **Target Directory:** `06_Prototype_Implementation/`
* **Tasks:**
  1. Organize clean modular directories:
     - `06_Prototype_Implementation/backend/` (FastAPI controller, routes, cache, dispatcher)
     - `06_Prototype_Implementation/workers/` (Agent & Executor daemons)
     - `06_Prototype_Implementation/frontend/` (React + Vite + Tailwind application)
     - `06_Prototype_Implementation/optimizer/` (Existing solver & Poisson generator)
  2. Install required Python packages into `.venv`:
     - `fastapi`, `uvicorn[standard]`, `psutil`, `fakeredis`, `redis`, `websockets`, `pydantic`.
  3. Verify Node.js (`v24.11.1`) and npm (`11.6.2`) availability for the frontend.

### Phase 2: Worker Daemon & Execution Layer (Member 1)
* **Goal:** Create independent, multi-port worker nodes that execute physical workloads and report realistic telemetry.
* **Deliverables:**
  1. `workers/executor.py`:
     - FastAPI app running on parameterized port (e.g. `--port 8001`).
     - Endpoint `POST /execute` accepting `{task_id, duration_sec, matrix_dim}`.
     - Spawns background thread performing real BLAS matrix multiplications (`numpy.dot`).
     - Tracks concurrent `active_task_count`.
  2. `workers/agent.py`:
     - Lightweight polling loop running every 2.0 seconds.
     - Collects base CPU/RAM via `psutil` combined with active worker stress.
     - Adds worker virtualization offsets (so Worker 1, 2, and 3 display distinct base and active usage instead of identical host CPU values).
     - Transmits payload to `POST http://localhost:8000/api/telemetry`.
  3. `workers/run_worker.py`:
     - CLI entrypoint to start both executor and agent in a single unified worker process.

### Phase 3: Controller Backend, Cache & Dispatcher (Member 3 & Member 2)
* **Goal:** Central orchestration hub handling telemetry, caching, mathematical optimization, and dispatching.
* **Deliverables:**
  1. `backend/app/core/cache.py`:
     - Dual-mode Redis client: connects to `redis://localhost:6379` if active; otherwise boots a built-in async in-memory key-value store with 10-second TTL auto-eviction.
  2. `backend/app/core/database.py`:
     - Lightweight audit logger persisting assignment history and solver latencies to SQLite / JSON (with optional MongoDB connection string support).
  3. `backend/app/api/telemetry.py`:
     - Ingests worker telemetry and refreshes cache under `cluster:worker:{id}`.
  4. `backend/app/api/tasks.py` & `backend/app/services/dispatcher.py`:
     - Ingests tasks from the generator.
     - Fetches all active workers from the cache (filtering out expired nodes).
     - Invokes `ortools_optimizer.py` to calculate optimal $X_{ij}$ assignments minimizing peak load.
     - Dispatches HTTP POST to target worker port (`http://localhost:800X/execute`).
     - *Algorithm Benchmark Mode:* Adds a toggle to run **Round-Robin** vs. **OR-Tools MILP** to directly compare load variance and prove optimization superiority.
  5. `backend/app/api/websocket.py`:
     - Maintains active WebSocket clients and broadcasts `CLUSTER_SNAPSHOT` payloads every 1.5 seconds.

### Phase 4: Operations Dashboard (Member 4)
* **Goal:** High-aesthetic, real-time command center interface for demonstrations.
* **Tech Stack:** React 18, Vite, Tailwind CSS, Lucide Icons, Chart.js.
* **Deliverables:**
  1. **Header & Cluster Status:** Live connectivity pill (Connected/Reconnecting), active worker count, queue depth, solver latency meter.
  2. **Worker Node Cards (`WorkerCard.jsx`):**
     - Live CPU progress bar and RAM meter (Used / Total MB).
     - Dynamic threshold styling:
       - 🟢 **Healthy:** CPU $< 60\%$
       - 🟡 **Moderate:** CPU $60\% - 84\%$
       - 🔴 **Heavy / Saturated:** CPU $\ge 85\%$
  3. **Real-Time Rolling Charts (`MetricsChart.jsx`):**
     - Smooth multi-line Chart.js graph tracking CPU % and RAM % across all workers over the last 30 time steps.
  4. **Task Execution Live Ticker (`TaskQueue.jsx`):**
     - Table of recent tasks showing Task ID, Workload Type, Assigned Worker, and Execution Status.
  5. **Interactive Simulation Control Bar (`ControlPanel.jsx`):**
     - Start/Stop Poisson traffic generator directly from the browser.
     - Slider for arrival rate $\lambda$ (0.5 to 5.0 tasks/sec).
     - "Inject Traffic Spike" burst button.
     - Comparison toggle: **OR-Tools MILP** vs. **Round-Robin**.

### Phase 5: Unified One-Click Launcher & Orchestration
* **Goal:** A single command to start the entire distributed system.
* **Deliverable:** `launch_local.py`
  - Starts FastAPI Backend (Port 8000).
  - Starts Worker 1 (Port 8001).
  - Starts Worker 2 (Port 8002).
  - Starts Frontend Dev Server (Port 5173 / 3000).
  - Checks health of all services before signaling ready.
  - Automatically opens default browser to the dashboard.
  - Captures `SIGINT` (Ctrl+C) to terminate all subprocesses cleanly without dangling ports.

---

## 4. Verification & Testing Matrix

| Test Scenario | Action | Expected Outcome |
| :--- | :--- | :--- |
| **1. Cluster Idle Baseline** | Start `launch_local.py` without traffic | All workers appear as 🟢 Healthy (CPU < 10%), Redis TTL updates every 2s, WebSocket streams normally. |
| **2. Single Task Dispatch** | Send 1 CPU-bound task | Solver assigns task to Worker with lowest projected load; Worker CPU spikes visibly on dashboard. |
| **3. Poisson Stream ($\lambda = 1.5$)** | Start traffic stream | Tasks arrive with exponential inter-arrival gaps; OR-Tools distributes tasks evenly without exceeding 85% CPU. |
| **4. Traffic Burst ($\lambda = 4.0$)** | Trigger burst | Both workers ramp up; solver maintains balanced peak load $Z$ rather than dumping all load on one worker. |
| **5. Worker Failover** | Kill Worker 2 process | After 10s TTL expiration, Worker 2 automatically drops out of the dashboard; all subsequent tasks route to Worker 1. |
| **6. MILP vs. Round-Robin** | Switch to Round-Robin mode | Load disparity increases; demonstrator can show high variance and potential saturation on Round-Robin vs smooth balance on OR-Tools. |
