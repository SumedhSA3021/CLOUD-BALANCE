# Member 2: Detailed File-by-File Technical Breakdown
**Project:** CloudBalance — Adaptive Multi-Resource Cloud Load Balancer  
**Role:** Member 2 – Workload Modeling & Decision Optimization  
**Student Name:** Sumedh  
**Modules Owned:** Module 2 (Realistic Job Traffic Generation) & Module 3 (Google OR-Tools Optimization Engine)

---

## Executive Summary: What is Member 2's Role?
In CloudBalance, Member 2 serves as the **"Traffic Generator & Brain"** of the entire distributed system.

Traditional load balancers (like standard Round-Robin or Least Connections) treat every server as identical and every incoming request as equal. In modern cloud environments, this is completely untrue:
1. **User traffic arrives in unpredictable, bursty waves** (e.g. flash sales, sudden viral spikes, quiet nights).
2. **Tasks have completely different resource demands** (some need heavy CPU calculations, some need huge RAM memory buffers).
3. **Servers run on different background loads** (one VM might be at 75% CPU while another is idle at 10%).

Member 2 solves this by:
1. **Generating realistic, mathematically bursty cloud traffic** using a **Poisson Arrival Process**.
2. **Assigning real computational payloads** (NumPy matrix operations) that push genuine physical vCPU and RAM usage onto worker servers (not fake `time.sleep()`).
3. **Formulating an intelligent mathematical optimizer** using **Google OR-Tools (Mixed-Integer Linear Programming - MILP)** that looks at live server metrics and finds the optimal server assignment to balance the cluster and prevent server crashes.
4. **Providing a Traffic CLI runner** to simulate everything locally or fire real live traffic across the internet to Google Cloud Platform (GCP).

---

## File Structure for Member 2

All Member 2 code lives under the `06_Prototype_Implementation/optimizer/` directory:

```
06_Prototype_Implementation/
└── optimizer/
    ├── simulate_traffic.py               # [File 4] CLI runner for local demo & live GCP traffic streaming
    ├── solver/
    │   └── ortools_optimizer.py          # [File 3] Google OR-Tools MILP optimization algorithm
    └── traffic_generator/
        ├── poisson_generator.py          # [File 1] Real-time Poisson process inter-arrival engine
        └── workloads.py                  # [File 2] Workload archetypes & physical NumPy execution logic
```

---

## FILE 1: `optimizer/traffic_generator/poisson_generator.py`

### 1. High-Level Summary
This file is responsible for **simulating realistic web traffic arrival times**. Instead of sending tasks like a boring, unrealistic metronome ticking strictly every 2 seconds, this file uses probability theory (the **Poisson Process** and the **Exponential Distribution**) to generate natural, bursty traffic where tasks sometimes arrive in quick clusters and sometimes with idle pauses.

### 2. The Core Mathematical Theory
* In probability and queuing theory (Kendall's $M/M/1$ and $M/M/k$ models used in cloud computing), independent random arrival events at an average rate $\lambda$ (lambda) follow a **Poisson Process**.
* If the number of arrivals in a time window follows a Poisson distribution, the **time between consecutive arrivals (Inter-arrival time, $dt$)** follows an **Exponential Distribution**.
* To generate random time delays $dt$ in Python, we use the **Inverse Transform Sampling Method**:
  $$dt = -\frac{\ln(1 - U)}{\lambda}$$
  * $U$: A uniformly distributed random floating number between $0$ and $1$ ($U \sim \text{Uniform}(0, 1)$).
  * $\lambda$ (lambda): The target average arrival rate (e.g. $\lambda = 1.5$ tasks per second).
  * $\ln$: Natural logarithm.
  * $dt$: The exact number of seconds to wait before spawning the next task.

### 3. Detailed Code Breakdown

```python
class PoissonTrafficGenerator:
    def __init__(self, arrival_rate_lambda: float = 1.0):
        self.arrival_rate_lambda = max(0.01, arrival_rate_lambda)
        self.is_running = False
```
* **`__init__`**: Initializes the generator with a default average rate $\lambda = 1.0$ tasks per second. The `max(0.01, ...)` ensures lambda is never zero or negative (which would cause a division-by-zero math error).

```python
    def set_lambda(self, new_lambda: float) -> None:
        self.arrival_rate_lambda = max(0.01, new_lambda)
```
* **`set_lambda`**: Allows dynamic updating of the traffic rate on the fly. For instance, during a presentation, you can dynamically crank $\lambda$ up from `1.0` to `5.0` to simulate a sudden flash-traffic burst and show how the system reacts.

```python
    def calculate_next_interarrival(self) -> float:
        u = random.random()
        u = min(u, 0.999999) # Avoid math domain error if u == 1.0
        dt = -math.log(1.0 - u) / self.arrival_rate_lambda
        return dt
```
* **`calculate_next_interarrival`**: Generates a random number $U$, caps it just under 1.0 to avoid `math.log(0)` (which would crash with a math domain error), and applies the formula $dt = -\ln(1 - U) / \lambda$.

```python
    async def stream_tasks(self) -> AsyncGenerator[Dict[str, Any], None]:
        self.is_running = True
        while self.is_running:
            dt = self.calculate_next_interarrival()
            await asyncio.sleep(dt)
            task = create_task_payload()
            task["interarrival_dt_sec"] = round(dt, 4)
            yield task
```
* **`stream_tasks`**: This is an asynchronous generator (`async for ... in generator.stream_tasks()`).
  * In each loop iteration, it calculates the next inter-arrival delay $dt$.
  * It pauses non-blockingly using `await asyncio.sleep(dt)` for that exact duration.
  * It creates a structured task dictionary using `create_task_payload()` (from `workloads.py`).
  * It stamps the delay `interarrival_dt_sec` onto the task and yields it to the caller in real time.

---

## FILE 2: `optimizer/traffic_generator/workloads.py`

### 1. High-Level Summary
This file defines **what a task actually is** and **how it physically stresses the cloud servers**.

In amateur academic projects, students often write `time.sleep(4)` to simulate a 4-second job. But `time.sleep()` tells the operating system kernel: *"Put this process to sleep; use 0% CPU and 0 MB of active RAM."* If you do that, Member 1's monitoring tools will see 0% CPU utilization, meaning your load balancer has no real metrics to balance!

`workloads.py` solves this by:
1. Defining **4 realistic workload profiles** (CPU-heavy, Memory-heavy, Balanced, Lightweight).
2. Implementing **`execute_physical_workload()`**, which runs **NumPy BLAS matrix multiplications** (`numpy.dot`). This forces the physical vCPU on the Ubuntu VM to hit 100% core utilization and allocates real multi-megabyte RAM buffers.

### 2. Workload Archetypes Defined in Code

| Archetype Name | CPU Demand (%) | RAM Demand (MB) | Matrix Dimension | Duration (s) | Real-world Equivalent |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`CPU_INTENSIVE`** | 35.0% | 256 MB | $2400 \times 2400$ | 4.0s | Heavy mathematical computation, crypto hashing, video compression. |
| **`MEMORY_INTENSIVE`** | 15.0% | 1024 MB | $4500 \times 4500$ | 5.0s | In-memory database query, image processing buffer, caching. |
| **`BALANCED_COMPUTE`** | 25.0% | 512 MB | $2000 \times 2000$ | 3.0s | Standard web API data processing, microservice request. |
| **`LIGHTWEIGHT_QUERY`**| 10.0% | 128 MB | $1000 \times 1000$ | 1.5s | Fast database lookup, ping/healthcheck, status query. |

### 3. Detailed Code Breakdown

```python
def create_task_payload(archetype: Dict[str, Any] = None) -> Dict[str, Any]:
    if archetype is None:
        archetype = np.random.choice(WORKLOAD_ARCHETYPES)

    task_id = f"task-{uuid.uuid4().hex[:6]}"
    return {
        "task_id": task_id,
        "type": archetype["type"],
        "cpu_demand_pct": float(archetype["cpu_demand_pct"]),
        "mem_demand_mb": int(archetype["mem_demand_mb"]),
        "duration_sec": float(archetype["duration_sec"]),
        "matrix_dim": int(archetype["matrix_dim"]),
        "created_at": time.time()
    }
```
* **`create_task_payload`**: Generates a standard task payload. If no archetype is specified, it randomly picks one from the table above. It attaches a unique ID (e.g. `task-b7a12e`) and a precise timestamp.

```python
def execute_physical_workload(matrix_dim: int, duration_sec: float) -> Dict[str, Any]:
    start_time = time.time()
    operations_count = 0

    # 1. Physical RAM Allocation
    buffer = np.random.rand(matrix_dim, matrix_dim).astype(np.float32)

    # 2. Continuous vCPU Stress
    while (time.time() - start_time) < duration_sec:
        _ = np.dot(buffer[:500, :500], buffer[:500, :500])
        operations_count += 1

    elapsed = time.time() - start_time
    return {
        "status": "COMPLETED",
        "elapsed_sec": round(elapsed, 3),
        "operations_performed": operations_count,
        "allocated_matrix_dim": matrix_dim
    }
```
* **`execute_physical_workload`**:
  * **Memory Stress:** `np.random.rand(matrix_dim, matrix_dim)` creates a 2D matrix of 32-bit floats. For $4500 \times 4500$, this physically reserves $\sim 81\text{ MB}$ per slice and saturates RAM memory bandwidth.
  * **CPU Stress:** `np.dot(...)` performs low-level BLAS/LAPACK floating-point operations (FLOPs) inside a `while` loop for the entire `duration_sec`. This pins the vCPU at 100% capacity during execution.
  * **Output:** Returns execution statistics (actual elapsed time and number of matrix multiplications completed).

---

## FILE 3: `optimizer/solver/ortools_optimizer.py`

### 1. High-Level Summary
This is the **mathematical core and algorithmic brain** of CloudBalance. It receives a batch of pending tasks and live metrics from the worker VMs, formulates the scheduling problem as a **Mixed-Integer Linear Program (MILP)**, and uses **Google OR-Tools** to find the mathematically optimal server assignment.

### 2. The Mathematical Formulation

#### A. Decision Variable ($X_{ij}$)
Let $N$ be the number of pending tasks, and $M$ be the number of active worker VMs.
We define a binary decision variable:
$$X_{ij} \in \{0, 1\} \quad \forall i \in \{1, \dots, N\}, \, j \in \{1, \dots, M\}$$
* $X_{ij} = 1$ if Task $i$ is assigned to Worker $j$.
* $X_{ij} = 0$ otherwise.

#### B. Constraint 1: Single Assignment
Every task must be assigned to **exactly one** server (no task can be split in half, duplicated, or dropped):
$$\sum_{j=1}^{M} X_{ij} = 1 \quad \forall i \in \{1, \dots, N\}$$

#### C. Constraint 2: CPU Safety Limit
The projected CPU utilization on Server $j$ (its current CPU usage + the CPU demands of all newly assigned tasks) must not exceed the safety cap (default 85%):
$$\text{Current\_CPU}_j + \sum_{i=1}^{N} \left(X_{ij} \times \text{Req\_CPU}_i\right) \le \text{Max\_CPU\_Limit} \quad (\text{e.g. } 85\%)$$

#### D. Constraint 3: RAM Safety Limit (OOM Crash Prevention)
The projected RAM usage on Server $j$ must not exceed 90% of its physical memory capacity:
$$\text{Current\_Mem\_MB}_j + \sum_{i=1}^{N} \left(X_{ij} \times \text{Req\_Mem\_MB}_i\right) \le 0.90 \times \text{Total\_Mem\_MB}_j$$

#### E. Objective Function: Min-Max Load Balancing
Rather than stuffing all tasks onto the first server that has space, we want to **minimize the peak CPU utilization** across the entire cluster.
We introduce an auxiliary continuous variable $Z$ representing the peak server load:
$$\text{Projected\_CPU}_j \le Z \quad \forall j \in \{1, \dots, M\}$$
$$\text{Objective:} \quad \min Z$$
By pulling down the ceiling $Z$, the solver is forced to spread tasks to less-utilized servers, keeping all servers balanced!

### 3. Detailed Code Breakdown

```python
def solve_task_assignment(
    pending_tasks: List[Dict[str, Any]],
    workers: List[Dict[str, Any]],
    max_cpu_limit: float = 85.0
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
```
* Takes `pending_tasks` (list of tasks to schedule), `workers` (list of live worker metrics from Redis), and `max_cpu_limit` (safety cap).

```python
    solver = pywraplp.Solver.CreateSolver("CBC")
    if not solver:
        solver = pywraplp.Solver.CreateSolver("SCIP")
```
* Instantiates Google OR-Tools' **CBC** (Coin-or branch and cut) solver, falling back to **SCIP** if CBC is not present. Both are industrial-grade MILP solvers.

```python
    # 1. Decision Variables X_ij
    x = {}
    for i in range(num_tasks):
        for j in range(num_workers):
            x[i, j] = solver.BoolVar(f"x_{i}_{j}")

    # 2. Auxiliary variable Z for Min-Max
    z = solver.NumVar(0.0, 100.0, "z")
```
* `solver.BoolVar()` creates the binary $0/1$ variables.
* `solver.NumVar(0.0, 100.0, "z")` defines continuous variable $Z$ bounded between 0% and 100%.

```python
    # 3. Constraint 1: Single assignment
    for i in range(num_tasks):
        solver.Add(solver.Sum(x[i, j] for j in range(num_workers)) == 1)

    # 4. Constraints 2 & 3: CPU and RAM caps per worker
    for j in range(num_workers):
        current_cpu = float(workers[j].get("cpu_percent", 0.0))
        current_mem = float(workers[j].get("memory_used_mb", 0.0))
        total_mem = float(workers[j].get("memory_total_mb", 4096.0))

        projected_cpu = current_cpu + solver.Sum(
            x[i, j] * float(pending_tasks[i].get("cpu_demand_pct", 10.0))
            for i in range(num_tasks)
        )
        solver.Add(projected_cpu <= max_cpu_limit)

        projected_mem = current_mem + solver.Sum(
            x[i, j] * float(pending_tasks[i].get("mem_demand_mb", 256.0))
            for i in range(num_tasks)
        )
        solver.Add(projected_mem <= (total_mem * 0.90))

        solver.Add(projected_cpu <= z) # Min-Max constraint
```
* Implements the exact mathematical formulas using `solver.Add()`.

```python
    # 5. Minimize peak load Z
    solver.Minimize(z)
    status = solver.Solve()
```
* Sets the objective to $\min Z$ and executes the solver.

```python
    if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        # Extract assignments where x[i, j] == 1
        ...
    else:
        # Graceful fallback heuristic if cluster is oversubscribed
        workers_sorted = sorted(workers, key=lambda w: w.get("cpu_percent", 0.0))
        fallback_worker = workers_sorted[0]["worker_id"]
        ...
```
* **Robust Error Handling:** If traffic is so insanely heavy that all servers are at 84% and no solution fits under the strict 85% cap, the solver returns `INFEASIBLE`. Instead of crashing, the code catches this and routes greedily to the server with the lowest current load as a graceful fallback.

---

## FILE 4: `optimizer/simulate_traffic.py`

### 1. High-Level Summary
This is the **command-line execution tool** that Member 2 runs. It ties `poisson_generator.py`, `workloads.py`, and `ortools_optimizer.py` together and provides two operational modes:
1. **Local Test Mode (Offline Demo):** Runs completely on your laptop with simulated mock workers. No GCP connection, no internet, and no cloud costs required! Perfect for testing and quick verification.
2. **Live Cloud Mode (Online Production):** Connects across the public internet to the Google Cloud Controller VM, sending tasks via HTTP POST requests in real time.

### 2. Command-Line Options
```bash
python optimizer/simulate_traffic.py [OPTIONS]

Options:
  --target-url TEXT    GCP Controller URL (e.g., http://34.x.x.x:8000). 
                       If omitted, runs in Local Demo Mode.
  --lambda FLOAT       Poisson arrival rate in tasks/sec (default: 1.5).
  --max-tasks INT      Total tasks to generate before stopping (default: 10, 0 = infinite).
```

### 3. Detailed Code Breakdown

```python
async def run_local_demo(arrival_lambda: float, max_tasks: int):
    generator = PoissonTrafficGenerator(arrival_rate_lambda=arrival_lambda)
    mock_workers = [
        {"worker_id": "worker-1", "cpu_percent": 25.0, "memory_used_mb": 1200, "memory_total_mb": 4096},
        {"worker_id": "worker-2", "cpu_percent": 45.0, "memory_used_mb": 2100, "memory_total_mb": 4096}
    ]
    ...
    async for task in generator.stream_tasks():
        assignments, meta = solve_task_assignment([task], mock_workers)
        # Updates mock workers and displays console results in real-time
```
* **`run_local_demo`**:
  * Creates two simulated worker VMs (`worker-1` starting at 25% CPU, `worker-2` starting at 45% CPU).
  * As each Poisson task arrives, it calls `solve_task_assignment`.
  * Demonstrates that the optimizer intelligently steers tasks to `worker-1` because `worker-2` is more heavily loaded.
  * Adjusts the simulated CPU up and lets it cool down over time.

```python
async def run_live_cloud_stream(target_url: str, arrival_lambda: float, max_tasks: int):
    generator = PoissonTrafficGenerator(arrival_rate_lambda=arrival_lambda)
    endpoint = f"{target_url.rstrip('/')}/api/tasks"

    async with httpx.AsyncClient(timeout=10.0) as client:
        async for task in generator.stream_tasks():
            res = await client.post(endpoint, json=task)
            ...
```
* **`run_live_cloud_stream`**:
  * Uses `httpx.AsyncClient` for high-performance non-blocking HTTP network requests.
  * Fires each generated task directly to the GCP Controller endpoint (`POST /api/tasks`).
  * Logs the inter-arrival delay $dt$, status codes, and network latency in real time.

---

## Summary Table: Member 2 Files at a Glance

| File Path | Role in System | Key Function / Class | Inputs | Outputs |
| :--- | :--- | :--- | :--- | :--- |
| `optimizer/traffic_generator/poisson_generator.py` | Mathematical traffic timing | `PoissonTrafficGenerator`, `calculate_next_interarrival` | $\lambda$ (arrival rate) | Real-time async stream of tasks with bursty delays $dt$ |
| `optimizer/traffic_generator/workloads.py` | Payload definitions & physical stress | `create_task_payload`, `execute_physical_workload` | Workload archetypes, matrix dimension | JSON task payload; physical vCPU core pinning & RAM buffers |
| `optimizer/solver/ortools_optimizer.py` | Mathematical optimization engine | `solve_task_assignment` | Pending tasks list, live VM metrics from Redis, CPU cap | Task-to-server assignments $[X_{ij}]$, solver latency (ms), status |
| `optimizer/simulate_traffic.py` | User CLI executable | `run_local_demo`, `run_live_cloud_stream` | `--target-url`, `--lambda`, `--max-tasks` | Live console logs of traffic, assignments, and HTTP transmission |
