import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AssignmentFeed } from "../components/AssignmentFeed";
import { ClientPanel } from "../components/ClientPanel";
import { ControlPanel } from "../components/ControlPanel";
import { Header } from "../components/Header";
import { WorkerCard } from "../components/WorkerCard";
import { ClientPage } from "../pages/ClientPage";
import { DashboardPage } from "../pages/DashboardPage";
import type { ClusterSnapshot, WorkerSnapshotItem } from "../lib/types";

const MOCK_WORKER: WorkerSnapshotItem = {
  worker_id: "worker-1",
  ip_address: "10.128.0.11",
  port: 8001,
  cpu_percent: 42.5,
  memory_percent: 50.0,
  memory_used_mb: 2048,
  memory_total_mb: 4096,
  active_tasks: 2,
  status: "HEALTHY",
  load_avg_1m: 0.85,
  in_flight_cpu_pct: 10,
  in_flight_mem_mb: 256,
};

const MOCK_SNAPSHOT: ClusterSnapshot = {
  type: "CLUSTER_SNAPSHOT",
  timestamp: "2026-11-11T12:00:00Z",
  workers: [MOCK_WORKER],
  recent_assignments: [
    {
      task_id: "tsk-abc123",
      client_id: "laptop-alpha",
      task_type: "CPU_INTENSIVE",
      cpu_demand_pct: 35,
      mem_demand_mb: 256,
      assigned_worker_id: "worker-1",
      scheduler: "ortools_milp",
      solver_latency_ms: 4.12,
      queue_wait_ms: 19.5,
      execution_ms: 85.0,
      status: "COMPLETED",
      degraded: false,
      timestamp: "2026-11-11T12:00:00Z",
    },
  ],
  clients: [
    {
      client_id: "laptop-alpha",
      req_per_sec: 4.2,
      queued: 1,
      total_sent: 42,
      avg_queue_wait_ms: 18.4,
      served_by: { "worker-1": 25, "worker-2": 17 },
    },
  ],
  queue_depth: 3,
  active_scheduler: "ortools_milp",
  lambda_total: 12.5,
  avg_solver_latency_ms: 4.12,
  degraded_mode: false,
  degraded_warning: null,
  paused: false,
};

// Mock react-chartjs-2 for fast unit tests in jsdom
vi.mock("react-chartjs-2", () => ({
  Line: () => <div data-testid="mock-line-chart" />,
  Bar: () => <div data-testid="mock-bar-chart" />,
}));

vi.mock("../lib/api", () => ({
  fetchSnapshotFallback: vi.fn(async () => MOCK_SNAPSHOT),
  fetchRecentTasks: vi.fn(async () => MOCK_SNAPSHOT.recent_assignments),
  fetchBenchmarkRuns: vi.fn(async () => []),
  submitTask: vi.fn(async () => ({ accepted: true })),
  switchScheduler: vi.fn(async () => ({
    status: "updated",
    active_scheduler: "round_robin",
  })),
  updateTrafficControl: vi.fn(async () => ({ status: "ok" })),
  killWorker: vi.fn(async () => ({ status: "killed" })),
  reviveWorker: vi.fn(async () => ({ status: "revived" })),
  runNewBenchmark: vi.fn(async () => ({})),
}));

describe("CloudBalance Frontend Components & Pages", () => {
  it("renders Header with live telemetry pills and active scheduler", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Header
          snapshot={MOCK_SNAPSHOT}
          connectionState="CONNECTED"
          isStale={false}
        />
      </MemoryRouter>
    );
    expect(screen.getByTestId("connection-pill")).toHaveTextContent("CONNECTED");
    expect(screen.getByTestId("active-scheduler-pill")).toHaveTextContent(
      "OR-Tools MILP"
    );
    expect(screen.getByText(/12.5 req\/s/i)).toBeInTheDocument();
  });

  it("renders WorkerCard with CPU, RAM, active tasks, and HEALTHY status pill", () => {
    render(<WorkerCard worker={MOCK_WORKER} />);
    expect(screen.getByTestId("worker-card-worker-1")).toBeInTheDocument();
    expect(screen.getByTestId("worker-status-worker-1")).toHaveTextContent(
      "HEALTHY"
    );
    expect(screen.getByText(/42.5%/i)).toBeInTheDocument();
    expect(screen.getByText(/2048/i)).toBeInTheDocument();
  });

  it("renders AssignmentFeed, ClientPanel, and ControlPanel", () => {
    render(
      <div>
        <ControlPanel
          activeScheduler="ortools_milp"
          lambdaTotal={12.5}
          paused={false}
          onSelectScheduler={async () => {}}
          onChangeLambda={async () => {}}
          onTogglePause={async () => {}}
          onReviveAllWorkers={async () => {}}
        />
        <ClientPanel clients={MOCK_SNAPSHOT.clients} />
        <AssignmentFeed assignments={MOCK_SNAPSHOT.recent_assignments} />
      </div>
    );
    expect(screen.getByTestId("client-card-laptop-alpha")).toBeInTheDocument();
    expect(screen.getByText("tsk-abc123")).toBeInTheDocument();
    expect(screen.getByText("CPU_INTENSIVE")).toBeInTheDocument();
    expect(screen.getByText(/Pause Queue/i)).toBeInTheDocument();
  });

  it("renders Ops Dashboard (/) and populates worker cards from snapshot without client cards", async () => {
    render(
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <DashboardPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByTestId("worker-card-worker-1")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("client-card-laptop-alpha")).not.toBeInTheDocument();
  });

  it("renders Laptop Client (/client) page with stream workload controls", async () => {
    render(
      <MemoryRouter
        initialEntries={["/client"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ClientPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Workload Stream Generator/i)
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /Start Stream/i })
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/Workload Mix Profile/i)
    ).toBeInTheDocument();
  });
});
