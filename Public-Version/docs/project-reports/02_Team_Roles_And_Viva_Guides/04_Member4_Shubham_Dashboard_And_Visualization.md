Absolutely. Based on the responsibilities in the image, this is \*\*Member 4 – Dashboard \& Visualization\*\*. Below is a \*\*detailed 6-slide version\*\* in the same format as the previous members, with enough technical detail for a project presentation while keeping the slides understandable.



```

SLIDE 1 — ROLE \& SCOPE



Title: Dashboard \& Visualization



Core Role:

\- Acts as the user-facing layer of the CloudBalance system.

\- Provides a live visual representation of server resources, tasks, and system activity.

\- Helps users understand how computational workloads are distributed across worker VMs.



Main Responsibilities:

1\. Develop the live dashboard using React.

2\. Display CPU and memory utilization of worker VMs.

3\. Display server status and availability.

4\. Display active tasks and task assignments.

5\. Create graphs for monitoring resource usage.

6\. Receive and display real-time updates from the backend.



Key Technologies:

\- React

\- Tailwind CSS

\- Chart.js

\- WebSocket Client



Main Concept:

Backend Data → WebSocket → React Dashboard → Real-Time Visualization

```



```

SLIDE 2 — REACT DASHBOARD \& UI DESIGN



Title: React Dashboard \& User Interface



Why React?

\- React is used to build the interactive CloudBalance dashboard.

\- It allows the interface to update individual components without refreshing the entire page.

\- Different dashboard components can display different types of system information.



Dashboard Components:

\- Server overview

\- CPU utilization cards

\- Memory utilization cards

\- Server status indicators

\- Active task list

\- Task assignment information

\- Resource usage charts



Tailwind CSS:

\- Used to design and style the dashboard.

\- Provides responsive layouts and reusable styling classes.

\- Helps create a clean and consistent user interface.



Visual:

CloudBalance Backend → React Components → Dashboard UI



Main Concept:

React manages the interface → Tailwind CSS manages the design

```



```

SLIDE 3 — SERVER \& RESOURCE MONITORING



Title: Server Monitoring \& Resource Visualization



\- The dashboard displays the current status of worker VMs.

\- Monitoring information is received from the backend.

\- CPU and memory usage are displayed so users can understand current resource utilization.



Information Displayed:

\- Server/VM name

\- Server status

\- CPU usage

\- Memory usage

\- Available resources

\- Current workload

\- Number of active tasks



Status Indicators:

\- Green → Server is available

\- Yellow → Server is under moderate load

\- Red → Server is heavily loaded or unavailable



Purpose:

\- Provides a quick overview of the current infrastructure.

\- Helps identify heavily loaded or underutilized VMs.

\- Makes resource utilization easier to understand.



Visual:

Worker VMs → Monitoring Data → FastAPI → React Dashboard

&#x20;                        ↓

&#x20;                CPU / Memory / Status

```



```

SLIDE 4 — CHARTS \& RESOURCE VISUALIZATION



Title: Resource Usage Graphs



\- Charts are used to convert numerical monitoring data into easy-to-understand visual information.

\- Chart.js is used to create CPU and memory usage graphs.

\- Historical points can be displayed to show how resource usage changes over time.



Charts:

\- CPU utilization over time

\- Memory utilization over time

\- Server workload comparison

\- Task activity information



Example:

Time → 10:00 → 10:05 → 10:10 → 10:15

CPU  →  35%  →  52%  →  68%  →  45%

RAM  →  40%  →  48%  →  60%  →  50%



Benefits:

\- Makes resource trends easier to identify.

\- Helps visualize workload changes.

\- Allows comparison between different worker VMs.

\- Helps evaluate the effectiveness of task scheduling.



Visual:

Monitoring Data → Chart.js → CPU/Memory Graphs

```



```

SLIDE 5 — REAL-TIME UPDATES WITH WEBSOCKETS



Title: Real-Time Dashboard Communication



\- The dashboard receives live system updates using a WebSocket client.

\- WebSockets maintain a continuous communication channel between the backend and dashboard.

\- This allows information to appear on the dashboard without repeatedly refreshing the page.



Live Information:

\- CPU usage

\- Memory usage

\- Server status

\- Active tasks

\- Task assignments

\- Task completion status

\- Worker VM updates



Process:

1\. Worker VM generates monitoring information.

2\. FastAPI receives the updated information.

3\. Backend processes and forwards the required data.

4\. WebSocket sends the update to the React dashboard.

5\. React updates the corresponding dashboard component.

6\. User sees the latest information immediately.



Main Concept:

Worker VMs → FastAPI → WebSocket → React → Updated Dashboard



Visual:

&#x20;       Real-Time Data

&#x20;             ↓

&#x20;       FastAPI Backend

&#x20;             ↓

&#x20;      WebSocket Channel

&#x20;             ↓

&#x20;       React Dashboard

&#x20;             ↓

&#x20;      Live UI Components

```



```

SLIDE 6 — OVERALL DASHBOARD INTEGRATION



Title: Dashboard Integration \& Data Flow



Inputs:

\- CPU and memory metrics from worker VMs

\- Server status information

\- Active task information

\- Task assignments

\- Task completion updates



Dashboard Processing:

\- FastAPI provides the required information to the frontend.

\- WebSocket delivers real-time updates.

\- React manages the dashboard components.

\- Tailwind CSS provides the user interface design.

\- Chart.js converts resource data into visual graphs.



Overall System Flow:



Worker VMs

&#x20;    ↓

Monitoring Data

&#x20;    ↓

FastAPI Backend

&#x20;    ↓

WebSocket

&#x20;    ↓

React Dashboard

&#x20;    ↓

┌───────────────────────────────┐

│ Server Status                 │

│ CPU \& Memory Usage            │

│ Active Tasks                  │

│ Task Assignments              │

│ Resource Usage Charts         │

└───────────────────────────────┘



Output:

\- Live view of CloudBalance infrastructure

\- Real-time CPU and memory monitoring

\- Visibility of active tasks and assignments

\- Visual representation of resource utilization

\- Easy monitoring of overall system performance

```



&#x20;### Optional final slide/diagram for your presentation



&#x20;If you want your part to look \*\*more professional\*\*, you can use this as the main architecture diagram:



```

&#x20;                   CLOUD BALANCE DASHBOARD



&#x20;                        React Frontend

&#x20;                             │

&#x20;              ┌──────────────┼──────────────┐

&#x20;              ↓              ↓              ↓

&#x20;         Server Status    Task Status    Resource Charts

&#x20;              │              │              │

&#x20;              └──────────────┼──────────────┘

&#x20;                             ↑

&#x20;                        WebSocket

&#x20;                             ↑

&#x20;                      FastAPI Backend

&#x20;                             ↑

&#x20;                   ┌─────────┴─────────┐

&#x20;                   ↓                   ↓

&#x20;             Worker VM 1          Worker VM 2

&#x20;             CPU / RAM             CPU / RAM

&#x20;                   │                   │

&#x20;                   └─────────┬─────────┘

&#x20;                             ↓

&#x20;                      Live Monitoring Data

```



&#x20;This gives your section a clear story:



&#x20;\*\*React builds the dashboard → WebSocket brings live data → Chart.js visualizes it → the user monitors the entire CloudBalance system in real time.\*\*

