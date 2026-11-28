# Member 2: Team Integration & Mentor Presentation Guide
**Project:** CloudBalance — Adaptive Multi-Resource Cloud Load Balancer  
**Role:** Member 2 – Workload Modeling & Decision Optimization  
**Target Audience:** Project Mentor / External Viva Examiners / Teammates

---

## 1. How Member 2 Fits into the Team Architecture

A distributed system cannot function in silos. CloudBalance is designed as a **closed-loop feedback control system**. Here is exactly how Member 2's code connects to every teammate:

```
                      +------------------------------------------+
                      |         MEMBER 2 (Sumedh)                |
                      |  Traffic Generator (Poisson Process)     |
                      +------------------------------------------+
                                           │
                                           │ HTTP POST /api/tasks
                                           ▼
                      +------------------------------------------+
                      |         MEMBER 3 (Nafisa)                |
                      |         FastAPI Central Backend          |
                      +------------------------------------------+
                        │                                    ▲
      Passes task batch │                                    │ Reads live VM
      and calls solver  │                                    │ snapshots
                        ▼                                    │
    +─────────────────────────────+                 +─────────────────────────────+
    |      MEMBER 2 (Sumedh)      |                 |      MEMBER 1 (Ananya)      |
    | Google OR-Tools Optimizer   |                 | Redis Cache                 |
    | (Solves MILP assignment)    |                 | (cluster:worker:{id})       |
    +─────────────────────────────+                 +─────────────────────────────+
                        │                                    ▲
      Returns optimal   │                                    │ Pushes live CPU,
      assignments       ▼                                    │ RAM & load every 2s
                      +------------------------------------------+
                      |         MEMBER 3 (Nafisa)                |
                      | Task Dispatcher & WebSocket Broadcaster  |
                      +------------------------------------------+
                        │                                    │
       POST :8001/execute│                                    │ WebSocket /ws/live
      (dispatches tasks)│                                    │
                        ▼                                    ▼
         +─────────────────────────────+      +─────────────────────────────+
         |      MEMBER 1 (Ananya)      |      |      MEMBER 4 (Shubham)     |
         | GCP Worker VMs (Ubuntu)     |      | React + Vite Dashboard      |
         | (Runs NumPy matrix FLOPs)   |      | (Displays live visual charts|
         +─────────────────────────────+      +─────────────────────────────+
```

---

## 2. Deep Dive: Handshakes with Each Teammate

### A. Handshake with Member 1 (Ananya – Sensing & Telemetry)
* **What Member 1 Provides:**
  * Member 1 deploys an agent (`agent.py`) on each Google Cloud Ubuntu worker VM.
  * Every 2.0 seconds, this agent samples `psutil.cpu_percent()`, `psutil.virtual_memory()`, and active task counts.
  * These readings are cached in Redis under `cluster:worker:{id}` with a 10-second Time-To-Live (TTL).
* **How Member 2 Uses It:**
  * When Member 2's optimizer (`ortools_optimizer.py`) is invoked, it reads these live Redis snapshots.
  * The current CPU % and current RAM usage form the baseline constraints of the Mixed-Integer Linear Program (MILP).
* **What Member 2 Gives Member 1:**
  * Member 2 created `execute_physical_workload()` in `workloads.py`. Member 1 embeds this function into `executor.py` on the worker VMs.
  * When a task arrives, it actually runs floating-point matrix multiplications, guaranteeing that Member 1's `psutil` agent observes **real, physical CPU spikes and RAM utilization**.

### B. Handshake with Member 3 (Nafisa – Backend & Dispatch)
* **What Member 2 Gives Member 3:**
  1. `simulate_traffic.py`: Member 2 streams generated Poisson tasks across the internet to Member 3's FastAPI endpoint: `POST http://<CONTROLLER_IP>:8000/api/tasks`.
  2. `ortools_optimizer.py`: Member 3 imports Member 2's solver directly into the backend.
* **How Member 3 Executes Member 2's Decisions:**
  * When tasks arrive, Member 3 calls:
    ```python
    assignments, meta = solve_task_assignment(pending_tasks, active_workers)
    ```
  * Member 2's solver returns the assignment matrix: e.g. `[{"task_id": "task-b7a12e", "assigned_worker_id": "worker-1"}]`.
  * Member 3 then makes an internal network call to dispatch the workload to that exact worker: `POST http://10.128.0.11:8001/execute`.
  * Member 3 logs the assignment and solver latency (ms) into MongoDB Atlas.

### C. Handshake with Member 4 (Shubham – Dashboard & Visualization)
* **How Member 2's Work is Visualized:**
  * Member 4 builds the React frontend.
  * As Member 2 injects Poisson traffic bursts, Member 4's dashboard displays:
    1. **Live Task Queue:** Evaluators see Member 2's tasks arriving in real time, labeled with their resource type (`CPU_INTENSIVE`, `MEMORY_INTENSIVE`).
    2. **Worker Cards:** Shows CPU and RAM rising and changing colors (Green $\to$ Yellow) as worker nodes execute Member 2's NumPy matrices.
    3. **Time-Series Charts:** Proves that Member 2's Google OR-Tools optimizer successfully keeps worker CPU utilization evenly balanced over time, preventing any single VM from bottlenecking or crashing.

---

## 3. The Complete Closed-Loop Execution Lifecycle

To explain this clearly to your mentor, describe the lifecycle of a single request in 5 steps:

```
[Step 1: Traffic Injection]
Member 2's Poisson generator on Client PC calculates dt = -ln(1 - U)/lambda.
It sleeps for dt seconds, then sends a CPU_INTENSIVE task (2400x2400 matrix, 4s duration) 
to FastAPI: POST /api/tasks.

                     │
                     ▼
[Step 2: Metric Retrieval]
FastAPI receives the task. It immediately queries Redis to fetch the current 
health of all active workers (reported by Member 1's psutil agent).
Worker 1: 30% CPU, 1500MB RAM | Worker 2: 70% CPU, 2800MB RAM.

                     │
                     ▼
[Step 3: Optimization Decision]
FastAPI calls Member 2's Google OR-Tools solver: solve_task_assignment().
The MILP solver evaluates constraints (CPU <= 85%, RAM <= 90%) and minimizes peak load.
Because Worker 2 is already at 70%, adding a 35% task would violate the 85% limit (70 + 35 = 105%).
The solver assigns the task to Worker 1 in 3.4 milliseconds.

                     │
                     ▼
[Step 4: Physical Workload Execution]
FastAPI dispatches the task to Worker 1 (POST http://10.128.0.11:8001/execute).
Worker 1 runs execute_physical_workload(): allocates a float32 matrix and computes np.dot()
continuously for 4 seconds, pinning Worker 1's CPU core to 100%.

                     │
                     ▼
[Step 5: Feedback & Re-Balancing]
Member 1's agent on Worker 1 samples the CPU spike (now 65%) and pushes it to Redis.
When the next task arrives from Member 2, the optimizer sees Worker 1 is now loaded,
and automatically steers the new task to Worker 2.
Member 4's React dashboard shows both VM cards balanced in real time.
```

---

## 4. Script: How to Explain Your Part to Your Mentor

Use this script during your meeting with your mentor. It starts with the big picture, explains your exact technical contributions, and explains how you tie the whole project together.

### The 2-Minute Elevator Pitch (Say this first):
> *"Good morning/afternoon, Ma'am. My role in Project CloudBalance is **Member 2: Workload Modeling & Decision Optimization**.*
> 
> *Traditional load balancers fail in cloud environments because they are blind to multi-dimensional resource demands: a task might need 90% CPU but only 20MB RAM, while another needs 2GB RAM but minimal CPU. If a load balancer makes naive guesses like Round-Robin, servers crash with Out-Of-Memory errors.*
> 
> *My responsibility covers two critical modules:*
> 1. *First, **Module 2: Job Traffic Generation**. I mathematically model realistic cloud traffic using a **Poisson Arrival Process**. Instead of static delays, tasks arrive in natural bursts. Furthermore, my tasks execute real **NumPy matrix operations**, driving genuine physical CPU and RAM stress on our Google Cloud Ubuntu VMs.*
> 2. *Second, **Module 3: The Optimization Engine**. I formulated our task allocation as a **Mixed-Integer Linear Programming (MILP)** problem and implemented it using **Google OR-Tools**. Under strict safety constraints—such as capping CPU at 85% and preventing memory crashes—my engine finds the mathematically optimal server mapping in 2 to 5 milliseconds.*
> 
> *My code runs hand-in-hand with my teammates: I consume real-time telemetry from Ananya's Redis cache, feed decisions to Nafisa's FastAPI dispatcher, and Shubham's React dashboard visualizes the balanced cluster."*

---

### The 5-Minute Technical Deep Dive (Walk through the files):

> *"To execute this, I have created four dedicated files:*
> 
> 1. *In `poisson_generator.py`, I implemented inverse transform sampling using the formula $dt = -\frac{\ln(1-U)}{\lambda}$. This calculates the inter-arrival delay between consecutive tasks. It runs as an asynchronous stream, allowing us to dynamically increase $\lambda$ to simulate heavy traffic spikes during our viva demo.*
> 
> 2. *In `workloads.py`, I defined 4 workload archetypes: CPU-intensive, Memory-intensive, Balanced, and Lightweight. I also authored `execute_physical_workload()`. Instead of using dummy `time.sleep()` which leaves the CPU idle at 0%, this function runs `numpy.dot()` matrix multiplications. This forces genuine floating-point operations on the virtual CPU cores, giving Ananya's monitoring agent real data to measure.*
> 
> 3. *In `ortools_optimizer.py`, I formulated the MILP problem. We define a binary decision variable $X_{ij}$ where 1 means Task $i$ goes to Server $j$. We enforce single assignment so no task is duplicated, enforce CPU $\le 85\%$ and RAM $\le 90\%$, and minimize the auxiliary variable $Z$ representing the cluster's peak load. If the cluster is completely saturated, I built a graceful fallback heuristic to avoid system crashes.*
> 
> 4. *In `simulate_traffic.py`, I built the CLI runner. It supports an offline local demo mode for instant testing with mock workers, and a live cloud mode that streams tasks across the internet to our GCP Controller VM."*

---

## 5. Viva Defense: Tough Questions Your Mentor Might Ask & Perfect Answers

### Q1: "Why did you use a Poisson arrival process? Why not just use `random.randint(1, 5)`?"
* **Your Answer:**
  > *"Ma'am, standard uniform random intervals (`random.randint`) do not reflect human or web behavior. In real cloud systems, request arrivals are independent events occurring at a known average rate—which is the textbook definition of a Poisson process. The Poisson distribution is the mathematical foundation for Kendall's queuing theory ($M/M/1$ and $M/M/k$ queues) universally adopted in cloud infrastructure research. Using Poisson gives us realistic traffic clustering: natural quiet periods followed by sudden rapid bursts, which is the only true way to test whether an adaptive load balancer can handle real-world traffic."*

---

### Q2: "Why Google OR-Tools? Why didn't you just use Round-Robin or Least Connections?"
* **Your Answer:**
  > *"Heuristics like Round-Robin or Least Connections are single-dimensional and greedy. For example, Least Connections routes a task to Server A simply because it has only 1 active connection, while Server B has 4. But if that 1 task on Server A is an enormous matrix calculation consuming 95% of its RAM, sending it another task will trigger an Out-Of-Memory (OOM) kernel panic and crash the VM.*
  > 
  > *Google OR-Tools allows us to model multiple resources (CPU, RAM, and server capacity) simultaneously as a Mixed-Integer Linear Program. It searches the global solution space and finds a mathematically optimal assignment in just 2 to 5 milliseconds, completely preventing hotspotting."*

---

### Q3: "What is a Mixed-Integer Linear Program (MILP)? What makes it 'Mixed' and 'Integer'?"
* **Your Answer:**
  > *"Ma'am, it is called **Integer** because our assignment decisions cannot be fractional. We cannot assign 30% of a task to VM-1 and 70% to VM-2; each task is an indivisible unit assigned as binary $0$ or $1$ ($X_{ij} \in \{0, 1\}$).*
  > 
  > *It is called **Mixed** because the problem combines discrete binary decision variables ($X_{ij}$) with continuous variables, such as server CPU percentages and our auxiliary min-max objective variable $Z$.*
  > 
  > *It is called **Linear Programming** because all our constraints—such as $\sum X_{ij} = 1$ and projected load equations—are strictly linear relationships ($Ax \le b$). Linear formulations guarantee that solvers like CBC can compute the global optimum in single-digit milliseconds without combinatorial explosion."*

---

### Q4: "What happens if all servers are already at 85% CPU and a new burst arrives?"
* **Your Answer:**
  > *"In an extreme traffic spike where all worker nodes have reached their 85% threshold, the MILP constraints cannot be strictly satisfied, meaning the solver returns an `INFEASIBLE` status.*
  > 
  > *In `ortools_optimizer.py`, I anticipated this edge case and implemented a graceful fallback heuristic. Rather than crashing or rejecting the request, the engine catches `INFEASIBLE`, identifies the worker with the lowest current CPU utilization, and routes the task there as an emergency measure while warning the backend. In a production cloud, this event would trigger GCP Auto-scaling to spin up additional worker VMs."*

---

### Q5: "Where does your code run? On GCP or on your local machine?"
* **Your Answer:**
  > *"My work spans both:
  > 1. `simulate_traffic.py` and `poisson_generator.py` run on my local client machine, acting as external cloud users sending live HTTP traffic across the internet to the cloud balancer.
  > 2. `ortools_optimizer.py` and `workloads.py` are hosted on GCP. The optimizer is called by Nafisa's FastAPI backend on the Controller VM, and the workload execution logic runs on Ananya's worker VMs to stress the hardware."*
