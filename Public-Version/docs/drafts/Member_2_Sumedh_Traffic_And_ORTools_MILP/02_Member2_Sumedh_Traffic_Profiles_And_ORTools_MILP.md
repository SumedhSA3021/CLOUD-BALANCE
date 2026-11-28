# Member 2 (Sumedh) — Traffic Generation, Resource Profiles & OR-Tools MILP Optimization Guide

**Role:** Modules 2 & 3 — Stochastic Poisson Workload Modeling, Real NumPy Execution & Google OR-Tools MILP Task Scheduler  
**Technologies:** Python 3.11, NumPy (`np.dot`), Google OR-Tools (`ortools.linear_solver.pywraplp` CBC/SCIP), Poisson Process, Matplotlib Benchmark Suite

---

## 1. Scope & Responsibilities in the Current Build

Member 2 owns the **Workload Modeling & Mathematical Decision Engine** of CloudBalance:
1. **Authoritative Server-Side Resource Profile Table (`backend/app/core/profiles.py`)**: Mapping each client `task_type` (`CPU_INTENSIVE`, `MEMORY_INTENSIVE`, `BALANCED_COMPUTE`, `LIGHTWEIGHT_QUERY`) to its exact CPU demand %, RAM demand MB, NumPy matrix dimension, and target duration.
2. **Stochastic Poisson Traffic Generator & CLI (`traffic/poisson_generator.py`, `traffic/workloads.py`, `traffic/cli.py`)**: Generating realistic, seedable bursty request streams using inverse-transform sampling ($dt = -\ln(1-U)/\lambda$) and demonstrating superposition of independent multi-laptop streams.
3. **Real NumPy Matrix Workload Executor (`worker/executor.py`)**: Executing genuine `np.dot(A, B)` floating-point matrix multiplications on the internal Worker VMs (`:8001–8003`) instead of dummy `time.sleep()`.
4. **Google OR-Tools MILP Scheduler & In-Flight Reservation Tracker (`backend/app/schedulers/ortools_milp.py`, `base.py`)**: Formulating micro-batch task placement as a Mixed-Integer Linear Program with min-max peak CPU objective, strict 85% CPU and 90% RAM safety caps, decaying in-flight reservations, and greedy lowest-projected-load fallback when oversubscribed.
5. **Baseline Schedulers & Reproducible Benchmark Suite (`round_robin.py`, `least_connections.py`, `benchmark/run_benchmark.py`)**: Comparing OR-Tools MILP against Round Robin and Least Connections on the exact same seeded multi-client trace.

---

## 2. Exact Files Owned by Member 2

| File Path | Key Classes / Functions | Purpose |
| :--- | :--- | :--- |
| [`backend/app/core/profiles.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/core/profiles.py) | `TaskType`, `ResourceProfile`, `TASK_PROFILES`, `resolve_task_profile()` | Server-side lookup table translating `task_type` into CPU%, RAM MB, `matrix_dim`, and `duration_sec`. |
| [`worker/executor.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/worker/executor.py) | `_run_numpy_dot_kernel()`, `create_worker_app()`, `POST /execute` | Internal Worker FastAPI service running real `np.dot` workloads and pushing live telemetry updates. |
| [`traffic/poisson_generator.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/traffic/poisson_generator.py) | `PoissonTrafficGenerator`, `superpose_seeded_streams()` | Seedable exponential inter-arrival generator ($dt = -\ln(1-U)/\lambda$) and multi-client stream superposition. |
| [`traffic/workloads.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/traffic/workloads.py) & [`traffic/cli.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/traffic/cli.py) | `WorkloadMix`, `ScenarioType`, `cb-traffic` CLI | Supports `--mix cpu|mem|balanced` and `--scenario steady|burst|ramp`. |
| [`backend/app/schedulers/base.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/schedulers/base.py) | `BaseScheduler`, `InFlightTracker`, `InFlightReservation` | Abstract scheduler interface and time-decaying in-flight resource reservation tracker. |
| [`backend/app/schedulers/ortools_milp.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/schedulers/ortools_milp.py) | `ORToolsMILPScheduler` | CBC/SCIP Mixed-Integer Linear Programming scheduler with 50ms time limit and degraded fallback. |
| [`backend/app/schedulers/round_robin.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/schedulers/round_robin.py) & [`least_connections.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/backend/app/schedulers/least_connections.py) | `RoundRobinScheduler`, `LeastConnectionsScheduler` | Baseline schedulers implementing the exact same `BaseScheduler.assign()` contract for live hot-swap. |
| [`benchmark/run_benchmark.py`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/benchmark/run_benchmark.py) | `run_all_benchmarks()` | Replays identical seeded 3-laptop Poisson traffic across all 3 schedulers and outputs CSV, Markdown, and PNG charts. |

---

## 3. Mathematical Formulation & Code Walkthrough

### A. Server-Side Resource Profile Table (`backend/app/core/profiles.py`)
Clients never declare their own CPU or RAM needs (preventing spoofing or misconfiguration). Instead, the Controller resolves each `task_type`:

| `task_type` | CPU Demand | RAM Demand | Matrix Dim (`np.dot`) | Target Duration | Client Portal Action |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `CPU_INTENSIVE` | **35.0%** | **256 MB** | $2400 \times 2400$ | `4.0 s` | Neural AI Inference & 4K Render |
| `MEMORY_INTENSIVE` | **15.0%** | **1024 MB** | $4500 \times 4500$ | `5.0 s` | In-Memory Big Data Graph Load |
| `BALANCED_COMPUTE` | **25.0%** | **512 MB** | $2000 \times 2000$ | `3.0 s` | Analytics Report Compiler |
| `LIGHTWEIGHT_QUERY` | **10.0%** | **128 MB** | $1000 \times 1000$ | `1.5 s` | Cloud Search & Instant DB Lookup |

### B. Poisson Arrival Process & Superposition (`traffic/poisson_generator.py`)
- **Inter-Arrival Formula**: Given arrival rate $\lambda$ (tasks/sec) and $U \sim \text{Uniform}(0, 1)$, the inter-arrival time is:
  $$dt = -\frac{\ln(1 - U)}{\lambda}$$
- **Superposition Property**: When $K$ client laptops independently generate Poisson streams with rates $\lambda_1, \lambda_2, \dots, \lambda_K$, the combined arrival stream at the Controller's single entry point is a Poisson process with total rate:
  $$\Lambda_{\text{total}} = \sum_{k=1}^{K} \lambda_k$$

### C. Google OR-Tools MILP Formulation (`backend/app/schedulers/ortools_milp.py`)
Given a micro-batch of $N$ tasks ($i \in \{0, \dots, N-1\}$) and $M$ active workers ($j \in \{0, \dots, M-1\}$):
1. **Decision Variables**:
   - Binary assignment variable $X_{i,j} \in \{0, 1\}$, where $X_{i,j} = 1$ iff task $i$ is assigned to worker $j$.
   - Continuous peak CPU variable $Z \in [0, 100]$.
   - Continuous peak memory percentage variable $M_{\text{peak}} \in [0, 100]$.
2. **Base Load (Telemetry + Decaying In-Flight Reservations)**:
   $$\text{BaseCPU}_j = \text{TelemetryCPU}_j + \text{InFlightCPU}_j, \qquad \text{BaseMem}_j = \text{TelemetryMem}_j + \text{InFlightMem}_j$$
3. **Hard Constraints**:
   - **Single Assignment**: $\sum_{j=0}^{M-1} X_{i,j} = 1 \quad \forall i$
   - **CPU Safety Cap ($\le 85\%$)**: $\text{BaseCPU}_j + \sum_{i=0}^{N-1} \text{cpu}_i \cdot X_{i,j} \le 85.0 \quad \forall j$
   - **RAM Safety Cap ($\le 90\%$ of Total RAM)**: $\text{BaseMem}_j + \sum_{i=0}^{N-1} \text{mem}_i \cdot X_{i,j} \le 0.90 \times \text{TotalMem}_j \quad \forall j$
   - **Min-Max Peak Linearization**: $\text{ProjectedCPU}_j \le Z$ and $\text{ProjectedMemPct}_j \le M_{\text{peak}} \quad \forall j$
4. **Objective Function**:
   $$\min \left( Z + 0.001 \cdot M_{\text{peak}} \right)$$
   This minimizes the highest CPU load across all workers while using memory utilization percentage as a tie-breaker (steering 1024 MB `MEMORY_INTENSIVE` tasks toward the 8 GB `worker-3` when CPU loads are tied).
5. **Degraded Fallback (`_degraded_fallback`)**:
   If a massive burst makes the 85% CPU / 90% RAM caps mathematically `INFEASIBLE`, the scheduler does not drop tasks; it switches to greedy lowest-projected-load routing, sets `degraded=True`, and emits a live warning banner to the Dashboard.

---

## 4. Benchmark Proof (`benchmark/results/benchmark_report.md`)

Replaying the exact same seeded 180-task multi-client burst stream across all 3 schedulers:

| Scheduler | Mean CPU StdDev (Lower = Better) | Peak CPU (%) | CPU Cap Violations (`>85%`) | RAM Cap Violations (`>90%`) | Mean Solver Latency |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`ortools_milp`** | **5.50%** | **95.36%** | **3** | **0** | `6.158 ms` |
| `round_robin` | 12.11% | 100.00% | 44 | 13 | `0.025 ms` |
| `least_connections` | 11.43% | 100.00% | 17 | 3 | `0.032 ms` |

---

## 5. Top Viva Questions & Answers for Member 2

1. **Q: Why use Mixed-Integer Linear Programming (MILP) instead of Least Connections?**  
   **A:** Least Connections only counts *how many* tasks a server has, treating a 10% CPU query and a 35% CPU / 1 GB RAM job as identical (`1 connection`). Moreover, when a batch of 10 tasks arrives, greedy heuristics assign one by one without global lookahead, whereas MILP solves the joint combinatorial placement across both CPU and RAM constraints in ~6 milliseconds.
2. **Q: Why do we need `InFlightTracker` (`backend/app/schedulers/base.py`)?**  
   **A:** Worker `psutil` telemetry arrives every 1.5–2.0 seconds, whereas micro-batches run every 200ms. Without in-flight reservations, 5 consecutive batches within 1 second would all read the same old telemetry and dump every task onto the same idle server. `InFlightTracker` reserves the task's CPU and RAM immediately upon scheduling and releases it as soon as worker telemetry absorbs the active task or completes execution.

