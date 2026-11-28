SLIDE 1 — ROLE & SCOPE

Title: Backend, Dispatch & Communication

Core Role:

\- Acts as the communication layer connecting all CloudBalance components.

\- Connects monitoring, optimization, worker VMs, database, and dashboard.

Main Responsibilities:

1\. Develop the backend using FastAPI.

2\. Receive monitoring data and task information.

3\. Receive task assignments from Google OR-Tools.

4\. Dispatch tasks to the selected Google Cloud VM.

5\. Store task and performance data in MongoDB.

6\. Send real-time updates to the dashboard using WebSockets.

Key Technologies:

\- Python

\- FastAPI

\- Redis

\- MongoDB

\- WebSockets

SLIDE 2 — FASTAPI BACKEND & API DESIGN

Title: FastAPI Backend & API Design

Why FastAPI?

\- Used to build the backend and connect different CloudBalance components.

\- Handles requests from worker VMs and other modules.

\- Manages task information and communication.

Key API Endpoints:

\- POST /api/telemetry — Receives CPU, memory, and load information from worker VMs.

\- POST /api/tasks — Receives new computational tasks.

\- POST /api/dispatch — Sends the task to the selected worker VM.

Pydantic:

\- Validates the data received by FastAPI.

\- Ensures task and monitoring data have the correct format.

Visual:

Worker VMs → FastAPI Backend → Other CloudBalance Components

SLIDE 3 — TASK DISPATCH & WORKER EXECUTION

Title: Task Dispatch Pipeline

Process:

1\. A new task is received by FastAPI.

2\. Task requirements are given to Google OR-Tools.

3\. OR-Tools decides which VM should receive the task.

4\. FastAPI receives the assignment.

5\. FastAPI sends the task to the selected Google Cloud VM.

6\. The worker VM executes the computational task.

7\. Task status and performance information are recorded.

Main Concept:

OR-Tools decides → FastAPI dispatches → Worker executes

Visual:

New Task → FastAPI → OR-Tools → Selected Worker VM → Task Execution

SLIDE 4 — REAL-TIME COMMUNICATION

Title: WebSockets for Live Updates

\- WebSockets allow the backend to send updates to the dashboard in real time.

\- The dashboard does not need to repeatedly request the latest information.

\- FastAPI sends updated information whenever it is available.

Live Information:

\- CPU usage

\- Memory usage

\- Server status

\- Active tasks

\- Task assignments

\- Task completion status

Flow:

Worker VMs → FastAPI → WebSocket → React Dashboard

Visual:

Show a simple real-time communication diagram between Worker VMs, FastAPI, WebSocket, and React Dashboard.

SLIDE 5 — MONGODB & DATA STORAGE

Title: Persistent Data Storage with MongoDB

MongoDB Stores:

\- Task details

\- CPU and memory requirements

\- Task assignments

\- Selected VM information

\- Task execution status

\- Performance data

\- Historical records

Purpose:

\- Keeps project data for future analysis.

\- Helps evaluate resource utilization and workload distribution.

\- Provides data for performance comparison.

Redis vs MongoDB:

\- Redis → Latest/current server information

\- MongoDB → Stored/historical information

Visual:

FastAPI → Redis (Current Data)

FastAPI → MongoDB (Historical Data)

SLIDE 6 — OVERALL SYSTEM INTEGRATION

Title: Backend Integration & Data Flow

Inputs:

\- Monitoring data from worker VMs

\- New tasks from the job generation module

\- Assignment decisions from OR-Tools

Backend Processing:

\- FastAPI connects the different components.

\- Redis provides current server information.

\- FastAPI dispatches tasks to the selected VM.

\- MongoDB stores important data.

\- WebSockets send live updates to the dashboard.

Overall System Flow:

Monitoring → FastAPI → OR-Tools → FastAPI → Selected Worker VM

FastAPI → MongoDB

FastAPI → WebSocket → React Dashboard