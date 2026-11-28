import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { Header } from "../components/Header";
import { ClientLoadPage, sampleExponentialGapMs } from "../pages/ClientLoadPage";
import { DashboardPage } from "../pages/DashboardPage";
import { OpsCenterPage } from "../pages/OpsCenterPage";
import { PublicTasksPage } from "../pages/PublicTasksPage";
import { buildHeavyHashRequest, buildLightCgpaRequest } from "../lib/taskPayloads";
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
  queue_length: 0,
};

const MOCK_SNAPSHOT: ClusterSnapshot = {
  type: "CLUSTER_SNAPSHOT",
  timestamp: "2026-11-11T12:00:00Z",
  workers: [
    MOCK_WORKER,
    { ...MOCK_WORKER, worker_id: "worker-2", cpu_percent: 88.5, status: "CRITICAL", queue_length: 4 },
    { ...MOCK_WORKER, worker_id: "worker-3", cpu_percent: 65.0, status: "MODERATE" },
  ],
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
};

// Mock react-chartjs-2 for fast unit tests in jsdom
vi.mock("react-chartjs-2", () => ({
  Line: () => <div data-testid="mock-line-chart" />,
  Bar: () => <div data-testid="mock-bar-chart" />,
}));

vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
  fetchSnapshotFallback: vi.fn(async () => MOCK_SNAPSHOT),
  fetchBenchmarkRuns: vi.fn(async () => []),
  fetchStatsSummary: vi.fn(async () => []),
  fetchTestStatus: vi.fn(async () => ({ state: "idle", sent: 0, ok: 0, failed: 0 })),
  fetchLiveDispatchStats: vi.fn(async () => ({
    window_seconds: 60,
    timestamps: [],
    labels: ["-1s", "now"],
    series: { "worker-1": [1, 2], "worker-2": [0, 1], "worker-3": [1, 1] },
    current_test_totals: { "worker-1": 3, "worker-2": 1, "worker-3": 2 },
    total_dispatched: 6,
  })),
  startAdminTest: vi.fn(async () => ({ state: "armed", test_id: "test-1234", sent: 0, ok: 0, failed: 0 })),
  stopAdminTest: vi.fn(async () => ({ state: "idle", sent: 0, ok: 0, failed: 0 })),
  downloadStatsFile: vi.fn(async () => {}),
  resetStats: vi.fn(async () => ({ status: "reset", detail: "cleared" })),
  submitContractTask: vi.fn(async () => ({
    result: { cgpa: 8.85, total_credits: 11, course_count: 3, scale: 10 },
    assigned_worker: "worker-1",
    queue_ms: 0.5,
    exec_ms: 1.2,
    total_ms: 2.1,
  })),
  runNewBenchmark: vi.fn(async () => ({})),
  loginAdmin: vi.fn(async (token: string) => {
    if (token !== "valid-admin-token") {
      throw new Error("Invalid admin bearer token");
    }
    return { authenticated: true, role: "admin" };
  }),
  verifyAdminSession: vi.fn(async (token: string) => {
    if (token !== "valid-admin-token") {
      throw new Error("Invalid admin bearer token");
    }
    return { authenticated: true, role: "admin" };
  }),
}));

describe("CloudBalance Frontend Components & Pages", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.clearAllMocks();
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

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

  it("does not expose Admin links or CSV download controls on PublicTasksPage (/)", () => {
    render(
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <PublicTasksPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/Workload Portal/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /\/ops/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Benchmark/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Ops Center/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/test_summary\.csv/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/test_log\.csv/i)).not.toBeInTheDocument();
  });

  it("renders ClientLoadPage publicly at /client without redirecting or exposing admin controls", async () => {
    window.history.pushState({}, "", "/client");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Client Load Generator/i)).toBeInTheDocument();
    });
    expect(window.location.pathname).toBe("/client");
    expect(screen.getByText(/Poisson Traffic Controls/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Ops Center/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/test_summary\.csv/i)).not.toBeInTheDocument();
  });

  it("isolates /client from admin routes, token inputs, and CSV buttons with exact rate and task-type inputs", async () => {
    const { container } = render(
      <MemoryRouter
        initialEntries={["/client"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ClientLoadPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("client-test-state")).toHaveTextContent("idle");
    });

    for (const link of screen.queryAllByRole("link")) {
      expect(link.getAttribute("href") ?? "").not.toMatch(/\/(ops|benchmark|admin)/i);
    }
    expect(screen.queryByLabelText(/Admin Token/i)).not.toBeInTheDocument();
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /csv|download|reset/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/test_summary\.csv/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/test_log\.csv/i)).not.toBeInTheDocument();

    const controls = container.querySelectorAll("input, select, textarea");
    expect(controls).toHaveLength(2);
    expect(screen.getByLabelText(/Tasks per second/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Task type/i)).toBeInTheDocument();
    expect(screen.getByText(/Keep this tab in the foreground/i)).toBeInTheDocument();
  });

  it("locks /ops and /benchmark behind Admin login gate without hardcoded tokens", async () => {
    window.history.pushState({}, "", "/ops");
    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Admin Token/i)).toBeInTheDocument();
    });
    const tokenInput = screen.getByLabelText(/Admin Token/i) as HTMLInputElement;
    expect(tokenInput.value).toBe("");
    expect(screen.queryByText(/Test Controls/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/test_summary\.csv/i)).not.toBeInTheDocument();
    expect(screen.queryByText("worker-1")).not.toBeInTheDocument();

    // Invalid token stays locked and surfaces an error
    fireEvent.change(tokenInput, { target: { value: "wrong-token" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Invalid admin bearer token/i);
    });
    expect(screen.queryByText(/Test Controls/i)).not.toBeInTheDocument();

    // Valid token unlocks /ops including CSV downloads & cluster panels
    fireEvent.change(tokenInput, { target: { value: "valid-admin-token" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    await waitFor(() => {
      expect(screen.getByText(/Test Controls/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /test_summary\.csv/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /test_log\.csv/i })).toBeInTheDocument();

    // Sign Out locks back immediately
    fireEvent.click(screen.getByRole("button", { name: /Sign Out/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/Admin Token/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Test Controls/i)).not.toBeInTheDocument();
  });

  it("locks /benchmark behind Admin login gate and unlocks Benchmark Lab after login", async () => {
    window.history.pushState({}, "", "/benchmark");
    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Admin Token/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Benchmark Results & Comparison/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/test_summary\.csv/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Admin Token/i), {
      target: { value: "valid-admin-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));

    await waitFor(() => {
      expect(screen.getByText(/Benchmark Results & Comparison/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /test_summary\.csv/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /test_log\.csv/i })).toBeInTheDocument();
  });

  it("renders Benchmark Lab (/benchmark) without least_connections or hot-swap control panel", async () => {
    sessionStorage.setItem("cb_admin_token", "valid-admin-token");
    render(
      <MemoryRouter
        initialEntries={["/benchmark"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <DashboardPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/2-Scheduler Deterministic Poisson Replay Benchmark/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Benchmark Results & Comparison/i)).toBeInTheDocument();
    expect(screen.getByText(/No completed tests yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/Least Connections/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Cluster Runtime Control Panel/i)).not.toBeInTheDocument();
  });

  it("renders Ops Center (/ops) with live worker telemetry, OVERLOADED badge, graphs, and MILP vs RR comparison table", async () => {
    const { fetchSnapshotFallback, fetchStatsSummary, fetchTestStatus } = await import("../lib/api");
    vi.mocked(fetchStatsSummary).mockResolvedValue([
      {
        test_id: "test-milp-1",
        mode: "milp",
        seed: "42",
        duration_s: "30",
        lambda_per_client: "3",
        heavy_ratio: "0.3",
        requests: "100",
        failed: "0",
        avg_ms: "120.0",
        p50_ms: "110.0",
        p95_ms: "200.0",
        max_ms: "250.0",
        max_queue_ms: "10.0",
        throughput_rps: "3.33",
        worker1_busy_ms: "4000.0",
        worker2_busy_ms: "4100.0",
        worker3_busy_ms: "3900.0",
        busy_time_stddev: "81.65",
        clients_seen: "3",
      },
      {
        test_id: "test-rr-1",
        mode: "round_robin",
        seed: "42",
        duration_s: "30",
        lambda_per_client: "3",
        heavy_ratio: "0.3",
        requests: "100",
        failed: "2",
        avg_ms: "150.0",
        p50_ms: "140.0",
        p95_ms: "250.0",
        max_ms: "300.0",
        max_queue_ms: "25.0",
        throughput_rps: "3.33",
        worker1_busy_ms: "6000.0",
        worker2_busy_ms: "3000.0",
        worker3_busy_ms: "3000.0",
        busy_time_stddev: "1414.21",
      },
    ]);
    vi.mocked(fetchTestStatus).mockResolvedValue({ state: "running", test_id: "test-live", mode: "milp", sent: 5, ok: 5, failed: 0 });
    sessionStorage.setItem("cb_admin_token", "valid-admin-token");
    render(
      <MemoryRouter
        initialEntries={["/ops"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <OpsCenterPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("worker-1")).toBeInTheDocument();
    });
    expect(screen.getByText("worker-2")).toBeInTheDocument();
    expect(screen.getByText("worker-3")).toBeInTheDocument();
    expect(screen.getByText(/OVERLOADED/i)).toBeInTheDocument();
    expect(screen.queryByText(/Load Source:/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("mock-line-chart")).toBeInTheDocument();
    expect(screen.getByTestId("mock-bar-chart")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeDisabled();
    await waitFor(() => {
      expect(screen.getByRole("columnheader", { name: "Difference %" })).toBeInTheDocument();
      expect(screen.getByRole("columnheader", { name: /Clients Seen/i })).toBeInTheDocument();
    });
    expect(fetchSnapshotFallback).toHaveBeenCalledWith("valid-admin-token");
    expect(screen.getByText(/test-milp-1/i)).toBeInTheDocument();
    expect(screen.getByText(/test-rr-1/i)).toBeInTheDocument();
    vi.mocked(fetchStatsSummary).mockResolvedValue([]);
    vi.mocked(fetchTestStatus).mockResolvedValue({ state: "idle", sent: 0, ok: 0, failed: 0 });
  });

  it("validates invalid CGPA input, handles 503 rejection, and shows clear 409 draining message on PublicTasksPage (/)", async () => {
    const { ApiError, submitContractTask } = await import("../lib/api");
    render(
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <PublicTasksPage />
      </MemoryRouter>
    );

    // Invalid grade (>10) is rejected client-side before dispatch
    const gradeInputs = screen.getAllByRole("spinbutton");
    fireEvent.change(gradeInputs[1], { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /Dispatch & Calculate CGPA/i }));
    await waitFor(() => {
      expect(screen.getByText(/between 0.0 and 10.0/i)).toBeInTheDocument();
    });

    // Valid grade sends request and surfaces worker 503 rejection accurately (not '200 OK')
    fireEvent.change(gradeInputs[1], { target: { value: "9.0" } });
    vi.mocked(submitContractTask).mockResolvedValueOnce({
      result: { status: "rejected_503", detail: "Worker queue full" },
      assigned_worker: "worker-2",
      queue_ms: 0,
      exec_ms: 0,
      total_ms: 5.0,
    });
    fireEvent.click(screen.getByRole("button", { name: /Dispatch & Calculate CGPA/i }));
    await waitFor(() => {
      expect(screen.getByText(/rejected_503/i)).toBeInTheDocument();
    });

    // HTTP 409 during draining displays clear friendly message on PublicTasksPage
    vi.mocked(submitContractTask).mockRejectedValueOnce(new ApiError("Test is draining", 409));
    fireEvent.click(screen.getByRole("button", { name: /Dispatch & Calculate CGPA/i }));
    await waitFor(() => {
      expect(screen.getByText(/test finishing, try again in a few seconds/i)).toBeInTheDocument();
    });
  });

  it("ClientLoadPage (a, b) schedules exponential Poisson arrivals around target rate, locks inputs while running, and halts cleanly on Stop", async () => {
    const { submitContractTask } = await import("../lib/api");

    // Verify exponential inter-arrival sample mean and std-dev both match 1000/rate
    // (a constant gap has std-dev 0 and fails even when mean == 1000/rate)
    let seed = 1337;
    const nextRand = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const samples = Array.from({ length: 1000 }, () => sampleExponentialGapMs(3, nextRand));
    const sampleMeanMs = samples.reduce((acc, val) => acc + val, 0) / samples.length;
    const sampleVarianceMs =
      samples.reduce((acc, val) => acc + (val - sampleMeanMs) ** 2, 0) / samples.length;
    const sampleStdMs = Math.sqrt(sampleVarianceMs);
    expect(Math.abs(sampleMeanMs - 1000 / 3)).toBeLessThan(25);
    expect(Math.abs(sampleStdMs - 1000 / 3)).toBeLessThan(35);

    // Deterministic seeded PRNG for fake-timer simulation
    let timerSeed = 42;
    vi.spyOn(Math, "random").mockImplementation(() => {
      timerSeed = (timerSeed * 1664525 + 1013904223) >>> 0;
      return timerSeed / 4294967296;
    });

    const originalSubmitImpl = vi.mocked(submitContractTask).getMockImplementation();
    const dispatchTimes: number[] = [];
    vi.mocked(submitContractTask).mockImplementation(async () => {
      dispatchTimes.push(Date.now());
      return {
        result: { final_hash: "abc", iterations: 150000 },
        assigned_worker: "worker-1",
        queue_ms: 0.5,
        exec_ms: 1.2,
        total_ms: 2.1,
      };
    });

    try {
      vi.useFakeTimers();
      window.history.pushState({}, "", "/client?id=tab-poisson-1");
      render(
        <MemoryRouter
          initialEntries={["/client?id=tab-poisson-1"]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <ClientLoadPage />
        </MemoryRouter>
      );

      const rateInput = screen.getByLabelText(/Tasks per second/i) as HTMLInputElement;
      const typeSelect = screen.getByLabelText(/Task type/i) as HTMLSelectElement;
      const startBtn = screen.getByRole("button", { name: /Start Poisson/i });
      const stopBtn = screen.getByRole("button", { name: /^Stop$/i });

      expect(rateInput.value).toBe("3");
      expect(typeSelect).not.toBeDisabled();
      expect(stopBtn).toBeDisabled();

      fireEvent.change(typeSelect, { target: { value: "heavy" } });
      fireEvent.click(startBtn);

      // Inputs and Start locked immediately while running
      expect(rateInput).toBeDisabled();
      expect(typeSelect).toBeDisabled();
      expect(startBtn).toBeDisabled();
      expect(stopBtn).not.toBeDisabled();

      // Advance 10s at 3 req/s -> ~30 tasks
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });

      const dispatchedCalls = vi.mocked(submitContractTask).mock.calls;
      expect(dispatchedCalls.length).toBeGreaterThanOrEqual(22);
      expect(dispatchedCalls.length).toBeLessThanOrEqual(38);
      const deltas = dispatchTimes.slice(1).map((t, idx) => t - dispatchTimes[idx]);
      expect(Math.max(...deltas) - Math.min(...deltas)).toBeGreaterThan(100);
      expect(dispatchedCalls[0][0]).toMatchObject({
        client_id: "tab-poisson-1",
        task_type: "heavy",
        size: 150000,
        client_rate: 3,
        client_task_type: "heavy",
        payload: {
          data: "cloudbalance-heavy-workload-2026",
          iterations: 150000,
        },
      });

      // Stop unlocks inputs and halts further dispatches
      fireEvent.click(stopBtn);
      expect(rateInput).not.toBeDisabled();
      expect(typeSelect).not.toBeDisabled();
      const countAtStop = vi.mocked(submitContractTask).mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(vi.mocked(submitContractTask).mock.calls.length).toBe(countAtStop);
    } finally {
      if (originalSubmitImpl) {
        vi.mocked(submitContractTask).mockImplementation(originalSubmitImpl);
      }
    }
  });

  it("ClientLoadPage (c) shows 409 draining notice and continues Poisson loop until Stop", async () => {
    const { ApiError, submitContractTask } = await import("../lib/api");
    vi.spyOn(Math, "random").mockReturnValue(0.5); // exp(-ln(0.5)/3)*1000 ~= 231ms
    vi.useFakeTimers();

    vi.mocked(submitContractTask).mockRejectedValueOnce(new ApiError("Test is draining", 409));

    window.history.pushState({}, "", "/client?id=tab-409");
    render(
      <MemoryRouter
        initialEntries={["/client?id=tab-409"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ClientLoadPage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: /Start Poisson/i }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(260);
    });
    expect(screen.getByText(/Test finishing, try again in a few seconds/i)).toBeInTheDocument();
    expect(screen.getByTestId("client-failed")).toHaveTextContent("1");

    // Loop stays alive and dispatches subsequent tick cleanly
    await act(async () => {
      await vi.advanceTimersByTimeAsync(260);
    });
    expect(vi.mocked(submitContractTask).mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("client-ok")).toHaveTextContent("1");

    fireEvent.click(screen.getByRole("button", { name: /^Stop$/i }));

    // Confirm shared payload builders match PublicTasksPage exact light/heavy shapes
    expect(buildLightCgpaRequest("public-web-client")).toEqual({
      client_id: "public-web-client",
      task_type: "light",
      payload: {
        courses: [
          { name: "Cloud Computing & Distributed Systems", credits: 4, grade: 9.0 },
          { name: "Algorithm Analysis & Optimization", credits: 4, grade: 8.5 },
          { name: "Database Engineering & Storage", credits: 3, grade: 9.0 },
        ],
      },
    });
    expect(buildHeavyHashRequest("public-web-client")).toEqual({
      client_id: "public-web-client",
      task_type: "heavy",
      size: 150000,
      payload: {
        data: "cloudbalance-heavy-workload-2026",
        iterations: 150000,
      },
    });
  });

  it("sends load_source 'external' when clicking Start on Ops Center (/ops)", async () => {
    const { fetchSnapshotFallback, fetchStatsSummary, fetchTestStatus, startAdminTest } = await import("../lib/api");
    vi.mocked(startAdminTest).mockClear();
    vi.mocked(fetchStatsSummary).mockResolvedValue([]);
    vi.mocked(fetchTestStatus).mockResolvedValue({ state: "idle", sent: 0, ok: 0, failed: 0 });
    sessionStorage.setItem("cb_admin_token", "valid-admin-token");
    render(
      <MemoryRouter
        initialEntries={["/ops"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <OpsCenterPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("worker-1")).toBeInTheDocument();
    });
    expect(fetchSnapshotFallback).toHaveBeenCalledWith("valid-admin-token");
    const startBtn = screen.getByRole("button", { name: /^Start$/i });
    await act(async () => {
      fireEvent.click(startBtn);
    });
    await waitFor(() => {
      expect(startAdminTest).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(startAdminTest)).toHaveBeenCalledWith(
      "valid-admin-token",
      expect.objectContaining({ load_source: "external" })
    );
  });

  it("removes Client Portal link/tab from admin header on /ops while keeping Ops Center and Benchmark Lab links", async () => {
    const { fetchSnapshotFallback } = await import("../lib/api");
    sessionStorage.setItem("cb_admin_token", "valid-admin-token");
    const { container } = render(
      <MemoryRouter
        initialEntries={["/ops"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <OpsCenterPage />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(fetchSnapshotFallback).toHaveBeenCalledWith("valid-admin-token");
    });

    expect(screen.getByRole("link", { name: /Ops Center/i })).toHaveAttribute("href", "/ops");
    expect(screen.getByRole("link", { name: /Benchmark Lab/i })).toHaveAttribute("href", "/benchmark");
    expect(screen.queryByRole("link", { name: /Client Portal/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Client Portal/i })).not.toBeInTheDocument();
    expect(container.querySelector('a[href="/client"], button[href="/client"]')).toBeNull();
    expect(container.querySelector('a[href="/"]')).toBeNull();
  });
});
