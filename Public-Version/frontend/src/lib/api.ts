/** HTTP API Client for CloudBalance Controller. */

import type {
  BenchmarkRun,
  ClusterSnapshot,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };

  const apiKey = import.meta.env.VITE_API_KEY;
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      if (errBody?.detail) {
        detail = String(errBody.detail);
      }
    } catch {
      // ignore json parse failure
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export async function fetchSnapshotFallback(
  token: string
): Promise<ClusterSnapshot> {
  return requestJson<ClusterSnapshot>("/api/v1/control/snapshot", {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function fetchBenchmarkRuns(token: string): Promise<BenchmarkRun[]> {
  return requestJson<BenchmarkRun[]>("/api/v1/benchmark/runs", {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function runNewBenchmark(
  token: string,
  seed = 42,
  numBatches = 18
): Promise<BenchmarkRun> {
  return requestJson<BenchmarkRun>(
    `/api/v1/benchmark/run?seed=${seed}&num_batches=${numBatches}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
}

// --- Shared Contract API Types and Helpers (D1, D2, D3, D4) ---

export interface TaskContractRequest {
  client_id: string;
  task_type: "light" | "heavy" | string;
  size?: number;
  sent_at?: number | string;
  payload?: any;
  client_rate?: number;
  client_task_type?: "light" | "heavy";
}

export interface TaskContractResponse {
  result: Record<string, any>;
  assigned_worker: string;
  queue_ms: number;
  exec_ms: number;
  total_ms: number;
}

export interface TestStatusResponse {
  state: "idle" | "armed" | "running" | "draining";
  test_id?: string | null;
  mode?: string | null;
  start_at?: number | null;
  duration_s?: number | null;
  seed?: number | null;
  lambda_per_client?: number | null;
  heavy_ratio?: number | null;
  load_source?: string | null;
  sent?: number | null;
  ok?: number | null;
  failed?: number | null;
}

export interface TestSummaryRow {
  test_id: string;
  mode: string;
  seed: string;
  duration_s: string;
  lambda_per_client: string;
  heavy_ratio: string;
  requests: string;
  failed: string;
  avg_ms: string;
  p50_ms: string;
  p95_ms: string;
  max_ms: string;
  max_queue_ms: string;
  throughput_rps: string;
  worker1_busy_ms: string;
  worker2_busy_ms: string;
  worker3_busy_ms: string;
  busy_time_stddev: string;
  clients_seen?: string;
}

export async function submitContractTask(
  req: TaskContractRequest
): Promise<TaskContractResponse> {
  return requestJson<TaskContractResponse>("/tasks", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function fetchTestStatus(): Promise<TestStatusResponse> {
  return requestJson<TestStatusResponse>("/test/status");
}

export async function startAdminTest(
  token: string,
  payload: {
    mode: string;
    duration_s: number;
    lambda_per_client: number;
    heavy_ratio: number;
    seed: number;
    load_source?: string;
  }
): Promise<TestStatusResponse> {
  return requestJson<TestStatusResponse>("/admin/test/start", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
}

export async function stopAdminTest(
  token: string
): Promise<TestStatusResponse> {
  return requestJson<TestStatusResponse>("/admin/test/stop", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function fetchStatsSummary(
  token: string
): Promise<TestSummaryRow[]> {
  return requestJson<TestSummaryRow[]>("/admin/stats/summary", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function downloadStatsFile(
  token: string,
  file: "summary" | "log" = "summary"
): Promise<void> {
  const res = await fetch(`${API_BASE}/admin/stats/download?file=${file}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    throw new ApiError(`Download failed: HTTP ${res.status}`, res.status);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = file === "log" ? "test_log.csv" : "test_summary.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export interface LiveDispatchStatsResponse {
  window_seconds: number;
  timestamps: number[];
  labels: string[];
  series: {
    "worker-1": number[];
    "worker-2": number[];
    "worker-3": number[];
  };
  current_test_totals: {
    "worker-1": number;
    "worker-2": number;
    "worker-3": number;
  };
  total_dispatched: number;
}

export async function fetchLiveDispatchStats(
  token: string
): Promise<LiveDispatchStatsResponse> {
  return requestJson<LiveDispatchStatsResponse>("/admin/stats/live", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function resetStats(
  token: string
): Promise<{ status: string; detail: string }> {
  return requestJson<{ status: string; detail: string }>("/admin/stats/reset", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export interface AdminAuthResponse {
  authenticated: boolean;
  role: string;
}

export async function loginAdmin(token: string): Promise<AdminAuthResponse> {
  return requestJson<AdminAuthResponse>("/admin/auth/login", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function verifyAdminSession(token: string): Promise<AdminAuthResponse> {
  return requestJson<AdminAuthResponse>("/admin/auth/verify", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

