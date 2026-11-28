SLIDE 1 — ROLE & SCOPE

Title: Monitoring & Data Collection

Core Role:

\- Acts as the sensing layer of CloudBalance — the first stage that produces real data.

\- Continuously observes worker VMs so every other module has accurate, up-to-date information to act on.

Main Responsibilities:

1\. Configure Google Cloud Compute Engine worker VMs (Ubuntu Server).

2\. Develop the monitoring agent that runs on every VM.

3\. Collect CPU usage, memory usage, load average, and running-task data.

4\. Send collected data to the FastAPI backend at regular intervals.

5\. Store the latest server metrics in Redis for instant access.

Key Technologies:

\- Python

\- psutil

\- Redis

SLIDE 2 — PSUTIL & METRICS COLLECTION

Title: Reading Server Health with psutil

Why psutil?

\- A Python library that reads a VM's real-time resource usage directly from the OS.

\- Lightweight — runs continuously on every worker VM without slowing it down.

Metrics Collected:

\- \`psutil.cpu\_percent()\` — current CPU usage (%)

\- \`psutil.virtual\_memory()\` — used vs. total memory

\- \`psutil.getloadavg()\` — average task queue length (1/5/15 min)

\- Running task count

Example Reading:

\- CPU: 62% | Memory: 3.4/8 GB | Load Avg: 1.15 | Running Tasks: 4

Visual:

Worker VM → psutil → Raw Metrics

SLIDE 3 — MONITORING AGENT PIPELINE

Title: Data Collection Pipeline

Process:

1\. Monitoring agent runs on each worker VM.

2\. Agent reads CPU, memory, load, and task data via psutil.

3\. Data is packaged (e.g., as JSON) with a VM ID and timestamp.

4\. Agent sends the data to the FastAPI backend.

5\. Backend forwards it to Redis for storage.

6\. Cycle repeats every few seconds.

Main Concept:

Collect → Package → Send → Store → Repeat

Visual:

VM 1 / VM 2 / VM N (Monitoring Agents) → FastAPI Backend → Redis

SLIDE 4 — REDIS & FAST DATA ACCESS

Title: Storing Live Data with Redis

Why Redis?

\- Stores data in memory, not on disk → near-instant reads and writes.

\- Keeps only the latest snapshot per VM — no unnecessary history.

\- Lets the optimizer check current server load without any delay.

Example:

\- Key: \`worker-2\` → Value: \`{cpu: 62, mem: 42.5, load: 1.15}\`

Redis vs MongoDB:

\- Redis → Current/latest server state (Member 1)

\- MongoDB → Stored/historical records (Member 3)

Visual:

Monitoring Agent → FastAPI → Redis (Current Data)

SLIDE 5 — WHY MONITORING MATTERS

Title: The Case for Real-Time Monitoring

Problem Without Monitoring:

\- Tasks get assigned blindly, without knowing which VM is actually free.

\- Leads to overloaded servers, slower task execution, and wasted idle capacity.

With Monitoring:

\- Every task assignment decision is based on real, current server conditions.

\- OR-Tools (optimization) cannot make a correct decision without fresh CPU/memory data.

\- Poor or delayed monitoring data directly causes poor load balancing — the entire system's accuracy depends on this stage.

Example:

\- If a VM's last reported CPU was 20% five minutes ago but is now at 95%, sending it a new task would overload it. Frequent, accurate monitoring prevents this.

Visual:

Accurate Data → Correct Optimization → Balanced Load

SLIDE 6 — OVERALL SYSTEM INTEGRATION

Title: Monitoring's Role in the Bigger Picture

Inputs:

\- Live CPU, memory, load, and task data from every worker VM

Processing:

\- Monitoring agents collect data continuously.

\- FastAPI receives and forwards the data.

\- Redis stores the latest state for quick lookup.

Outputs Used By:

\- OR-Tools (Member 2) — for task assignment decisions

\- Dashboard (Member 4) — for live CPU/memory/status display

Overall System Flow:

Worker VMs → Monitoring Agent → FastAPI → Redis → OR-Tools / Dashboard