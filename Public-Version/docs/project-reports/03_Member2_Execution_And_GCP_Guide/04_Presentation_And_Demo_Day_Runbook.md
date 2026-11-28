# Member 2: Demo Day & Viva Runbook
**Project:** CloudBalance — Adaptive Multi-Resource Cloud Load Balancer  
**Role:** Member 2 – Workload Modeling & Decision Optimization (Sumedh)  
**Quick Reference Sheet for Presentation Day**

---

## 1. Fast Command Cheat Sheet

### Mode A: 100% Offline Local Demo (Zero GCP / No Internet Needed)
Use this if the internet is down, Wi-Fi is spotty, or GCP VMs are offline. It runs completely on your laptop using mock workers:

```powershell
# Open terminal inside 06_Prototype_Implementation folder:
cd "C:\Users\sumed\Desktop\Minor Project\06_Prototype_Implementation"

# 1. Normal Poisson Traffic (1.5 tasks/sec, 10 tasks)
python optimizer/simulate_traffic.py --lambda 1.5 --max-tasks 10

# 2. Sudden Flash Spike Traffic (4.0 tasks/sec, 25 tasks)
python optimizer/simulate_traffic.py --lambda 4.0 --max-tasks 25
```

---

### Mode B: Live Cloud Mode (Connected to GCP)
Use this when presenting the live end-to-end distributed system on Google Cloud:

```powershell
# Point to your Controller's External IP
python optimizer/simulate_traffic.py --target-url http://<CONTROLLER_EXTERNAL_IP>:8000 --lambda 1.5 --max-tasks 30
```

---

## 2. Screen Setup Checklist for the Presentation

Before your mentor sits down, have these 3 windows open and arranged side-by-side:

| Window # | What to Display | Purpose |
| :---: | :--- | :--- |
| **Window 1 (Left Half)** | **Web Browser:** `http://<CONTROLLER_EXTERNAL_IP>:3000` | Shows the live React Dashboard, active worker health cards (Green $\to$ Yellow), and real-time CPU/RAM graphs. |
| **Window 2 (Top Right)** | **VS Code / Editor:** Member 2 files (`poisson_generator.py`, `workloads.py`, `ortools_optimizer.py`) | Ready to walk the mentor through the mathematical equations, constraints, and NumPy execution logic. |
| **Window 3 (Bottom Right)** | **Terminal:** Prompt inside `06_Prototype_Implementation/` | Ready to run `simulate_traffic.py` to trigger the live traffic stream on command. |

---

## 3. The 4-Phase Live Demonstration Script

When your mentor says *"Show me your demonstration"*, follow this 4-step sequence:

### Phase 1: Show Cluster Idle Baseline (30 seconds)
* Point to Window 1 (React Dashboard).
* Say: *"Ma'am, as you can see, our cluster is currently in a steady idle baseline state. Both GCP worker nodes are reporting healthy status at ~2% CPU and ~15% RAM. Redis is refreshing this telemetry every 2 seconds via Ananya's psutil agent."*

### Phase 2: Launch Normal Poisson Stream (1 minute)
* Switch to Window 3 (Terminal) and run:
  ```powershell
  python optimizer/simulate_traffic.py --target-url http://<IP>:8000 --lambda 1.5 --max-tasks 15
  ```
* Point out the inter-arrival delays ($dt$):
  * *"Notice that the tasks do not arrive at static intervals; their inter-arrival time $dt$ varies according to our Poisson Exponential sampling ($dt = -\ln(1-U)/\lambda$)."*
  * *"Each task has a distinct archetype—some are CPU-intensive, some are Memory-intensive."*

### Phase 3: Show the Optimization & Execution Feedback Loop (1 minute)
* Look back at Window 1 (Dashboard):
  * *"As Nafisa's backend receives my tasks, it invokes my Google OR-Tools solver. The solver assigns Task 1 to Worker 1. Worker 1's executor immediately begins physical NumPy matrix multiplications."*
  * *"Notice Worker 1's CPU gauge climbs to 55% and turns Yellow. When Task 2 arrives, the solver detects that Worker 1 is under load and dynamically steers Task 2 to Worker 2."*
  * *"On the time-series chart, both workers are sharing the load evenly—neither server is overloaded."*

### Phase 4: Inject a High-Traffic Flash Spike (1 minute)
* Run high burst:
  ```powershell
  python optimizer/simulate_traffic.py --target-url http://<IP>:8000 --lambda 5.0 --max-tasks 30
  ```
* Explain:
  * *"Now I have increased $\lambda$ to 5.0 tasks per second. Even under this heavy burst, our MILP constraints strictly enforce that neither node exceeds our 85% CPU or 90% RAM ceiling."*
  * *"If this were Round-Robin, it would have blindly dumped tasks onto already-stressed nodes and caused a server crash."*

---

## 4. Key Formulas & Numbers to Keep in Mind

| Concept | Formula / Value | Explanation in 1 Sentence |
| :--- | :--- | :--- |
| **Poisson Inter-arrival ($dt$)** | $dt = -\frac{\ln(1 - U)}{\lambda}$ | Inverse transform sampling of Exponential Distribution yielding realistic delays. |
| **Decision Variable** | $X_{ij} \in \{0, 1\}$ | Binary variable: 1 if Task $i$ goes to Worker $j$, 0 otherwise. |
| **Single Assignment Constraint** | $\sum_{j=1}^M X_{ij} = 1$ | Every task is assigned to exactly one server (no duplicates, no drops). |
| **CPU Safety Cap** | $\text{Proj\_CPU}_j \le 85\%$ | Prevents node starvation and thermal throttling. |
| **RAM Safety Cap** | $\text{Proj\_RAM}_j \le 90\%$ | Strictly prevents Out-Of-Memory (OOM) operating system crashes. |
| **Objective Function** | $\min Z$ subject to $\text{Proj\_CPU}_j \le Z$ | Min-Max load balancing: minimizes peak load to pull all servers into balance. |
| **Solver Latency** | **$2 - 5\text{ milliseconds}$** | Google OR-Tools solves the assignment in single-digit ms, adding zero noticeable lag. |
