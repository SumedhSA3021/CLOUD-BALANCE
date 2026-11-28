# Member 4 (Shubham) — React 18 Ops Dashboard, Interactive Client Portal & Real-Time Visualization Guide

**Role:** Module 4 — Operations Center Dashboard (`/`), Interactive Client Portal (`/client`), 3-Scheduler Benchmark UI (`/benchmark`), Chart.js Time-Series Graphs & Resilient WebSocket Client  
**Technologies:** React 18, TypeScript, Vite, Tailwind CSS, Chart.js (`react-chartjs-2`), Lucide Icons, WebSocket API with Exponential-Backoff Reconnect

---

## 1. Scope & Responsibilities in the Current Build

Member 4 owns the **User-Facing Visualization & Interactive Client Layer** of CloudBalance. All three frontend routes (`/`, `/client`, and `/benchmark`) are compiled into `frontend/dist` and served directly by the Controller on port `:8000` so the entire team connects through a **single URL**.

Your exact responsibilities in the codebase are:
1. **Main Operations Dashboard (`/` — `frontend/src/pages/DashboardPage.tsx`)**:
   - **Top Telemetry Header (`Header.tsx`)**: Displays live WebSocket connection status (`CONNECTED` / `RECONNECTING`), active scheduler pill (`OR-Tools MILP`, `Round Robin`, `Least Connections`), total arrival rate $\Lambda$ (`req/s`), queue depth, and average solver latency (`ms`).
   - **Live Worker VM Cards (`WorkerCard.tsx`)**: One card per internal Worker VM (`worker-1`, `worker-2`, `worker-3`) showing live CPU progress bar, RAM used/total MB, active task count, 1-minute load average, status badge (`HEALTHY` green, `MODERATE` amber, `CRITICAL` red), and a simulated **Kill / Revive** toggle button for failover demos.
   - **Rolling Real-Time Resource Charts (`MetricsChart.tsx`)**: Chart.js line chart tracking a rolling 60-point window of CPU% and RAM% across all active workers, with a visible 85% CPU / 90% RAM safety cap line.
   - **Per-Laptop Client Streams Panel (`ClientPanel.tsx`)**: Displays every connected teammate's device (`laptop-alpha`, `laptop-beta`, `mobile-1`, etc.), their live `req/s`, average queue wait (`ms`), and proportional color-coded badges showing **which Worker VMs served how many of their requests** (`served_by`).
   - **Live Assignment Feed (`AssignmentFeed.tsx`)**: Real-time table of the last 20 scheduled tasks showing `task_id`, `client_id`, `task_type`, CPU/RAM demand, assigned Worker VM, scheduler used, solver latency, and `ASSIGNED` / `COMPLETED` status.
   - **Runtime Control Panel (`ControlPanel.tsx`)**: Instant buttons to hot-swap between **OR-Tools MILP**, **Round Robin**, and **Least Connections**, adjust global $\lambda$, inject a 15-task burst spike, pause/resume the queue, or revive all workers.
2. **Interactive Client Portal (`/client` — `frontend/src/pages/ClientPage.tsx`)**:
   - Opened on teammates' phones and laptops.
   - Provides **4 interactive cloud application modules** (*1. Cloud Search & Instant DB Lookup* $\rightarrow$ `LIGHTWEIGHT_QUERY`, *2. Analytics Report Compiler* $\rightarrow$ `BALANCED_COMPUTE`, *3. Neural AI Inference Studio* $\rightarrow$ `CPU_INTENSIVE`, *4. In-Memory Big Data Graph Engine* $\rightarrow$ `MEMORY_INTENSIVE`), a **Live Worker VM load strip**, **1-tap device ID presets** (`laptop-alpha`, `laptop-beta`, `laptop-gamma`, `mobile-1`, `mobile-2`), an **automated Poisson stream generator**, and a **live table of this device's own requests** showing which internal Worker VM served each click.
3. **3-Scheduler Benchmark Comparison Page (`/benchmark` — `frontend/src/pages/BenchmarkPage.tsx`)**:
   - Bar charts and comparison tables contrasting OR-Tools MILP vs. Round Robin vs. Least Connections on CPU standard deviation, peak CPU/RAM, and cap violations.
4. **Resilient WebSocket Hook & API Client (`frontend/src/hooks/useWebSocket.ts`, `frontend/src/lib/api.ts`)**:
   - Connects to `ws://<host>:8000/ws`, parses `CLUSTER_SNAPSHOT` frames every 1.5s, reconnects with exponential backoff if disconnected, polls `GET /api/v1/control/snapshot` as an automatic fallback, and retries task submissions via `GET /api/v1/tasks/submit` if a mobile hotspot drops a keep-alive `POST` socket.

---

## 2. Exact Files Owned by Member 4

| File Path | Component / Hook | Purpose |
| :--- | :--- | :--- |
| [`frontend/src/pages/DashboardPage.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/pages/DashboardPage.tsx) | `DashboardPage` (`/`) | Main Operations Center combining WorkerCards, MetricsChart, ControlPanel, ClientPanel, and AssignmentFeed. |
| [`frontend/src/pages/ClientPage.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/pages/ClientPage.tsx) | `ClientPage` (`/client`) | Interactive Client Portal with 4 cloud app widgets, live worker strip, Poisson streamer, and per-device task feed. |
| [`frontend/src/pages/BenchmarkPage.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/pages/BenchmarkPage.tsx) | `BenchmarkPage` (`/benchmark`) | Visualizes 3-scheduler benchmark metrics using Chart.js bar charts and summary tables. |
| [`frontend/src/components/WorkerCard.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/components/WorkerCard.tsx) | `WorkerCard` | Displays per-VM CPU/RAM bars, active tasks, `HEALTHY`/`MODERATE`/`CRITICAL` pill, and Kill/Revive button. |
| [`frontend/src/components/MetricsChart.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/components/MetricsChart.tsx) | `MetricsChart` | Rolling 60-point Chart.js time-series line graph with CPU% and RAM% tabs. |
| [`frontend/src/components/ClientPanel.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/components/ClientPanel.tsx) | `ClientPanel` | Per-laptop telemetry cards showing `req/s`, `total_sent`, and `served_by` worker distribution bars. |
| [`frontend/src/components/ControlPanel.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/components/ControlPanel.tsx) | `ControlPanel` | Scheduler hot-swap toggles, $\lambda$ slider, burst spike button, and pause/resume controls. |
| [`frontend/src/components/AssignmentFeed.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/components/AssignmentFeed.tsx) & [`Header.tsx`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/components/Header.tsx) | `AssignmentFeed`, `Header` | Live assignment table (last 20 tasks) and top cluster telemetry navigation bar. |
| [`frontend/src/hooks/useWebSocket.ts`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/hooks/useWebSocket.ts) | `useWebSocket()` | Custom React hook managing WebSocket lifecycle, rolling 60-point history buffer, stale detection, and HTTP fallback. |
| [`frontend/src/lib/api.ts`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/lib/api.ts) & [`types.ts`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/frontend/src/lib/types.ts) | `submitTask()`, TypeScript interfaces | Typed REST client and strict TypeScript definitions matching backend Pydantic schemas. |

---

## 3. Data Flow in the Frontend (`WebSocket -> React State -> Chart.js`)

```text
FastAPI WebSocketBroadcaster (/ws every 1.5s)
        │
        ▼  JSON: { type: "CLUSTER_SNAPSHOT", workers: [...], recent_assignments: [...], clients: [...] }
useWebSocket() Hook (frontend/src/hooks/useWebSocket.ts)
        ├──► Updates `snapshot` state (triggers instant re-render of WorkerCard, ClientPanel, AssignmentFeed)
        ├──► Appends worker CPU% & RAM% to `history` ring buffer (max 60 points -> MetricsChart)
        └──► Tracks last message timestamp (`isStale` indicator if no message for >4.5s + HTTP fallback poll)
```

---

## 4. Top Viva Questions & Answers for Member 4

1. **Q: Why use WebSockets (`/ws`) for the dashboard instead of regular HTTP `fetch()` polling?**  
   **A:** With multiple dashboards and client laptops watching live cluster telemetry every 1.5 seconds, repeated HTTP polling adds connection overhead and header bloat. A persistent WebSocket connection lets the FastAPI backend push a single `CLUSTER_SNAPSHOT` frame simultaneously to all connected browsers the instant a scheduler switch, worker kill, or telemetry tick happens.
2. **Q: What happens on the frontend if the WebSocket connection drops on a mobile hotspot?**  
   **A:** `useWebSocket.ts` implements **exponential-backoff reconnection** (`500ms -> 1s -> 2s -> 4s`) AND runs a fallback HTTP poll (`GET /api/v1/control/snapshot`) whenever the socket is not `CONNECTED`, ensuring the dashboard and `/client` page never freeze.
3. **Q: How does the `/client` page prove that CloudBalance is working in real time?**  
   **A:** When a teammate clicks any of the 4 interactive cloud service cards on `/client` (e.g., *Run AI Job* or *Load into RAM*), their browser only sends `{ client_id, task_type }`. Within ~200ms, the live table and worker strip on their screen show which internal Worker VM (`worker-1`, `worker-2`, or `worker-3`) was selected by `ortools_milp`, the exact server-resolved resource demand (`35% CPU / 256 MB`), and the real NumPy execution duration (`~540 ms`).

