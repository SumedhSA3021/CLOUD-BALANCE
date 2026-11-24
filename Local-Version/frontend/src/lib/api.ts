/** HTTP API Client for CloudBalance Controller (/api/v1). */

import type {
  Assignment,
  BenchmarkRun,
  ClusterSnapshot,
  SchedulerName,
  TaskSubmissionResponse,
  TaskType,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

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
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function submitTask(
  clientId: string,
  taskType: TaskType
): Promise<TaskSubmissionResponse> {
  try {
    return await requestJson<TaskSubmissionResponse>("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, task_type: taskType }),
    });
  } catch (err) {
    // On iOS Safari / mobile hotspot, if a half-closed HTTP/1.1 keep-alive socket throws
    // "Load failed" or "Failed to fetch" on POST, immediately fall back to idempotent GET.
    const q = new URLSearchParams({
      client_id: clientId,
      task_type: taskType,
      _t: String(Date.now()),
    });
    try {
      return await requestJson<TaskSubmissionResponse>(
        `/api/v1/tasks/submit?${q.toString()}`,
        { method: "GET" }
      );
    } catch {
      throw err;
    }
  }
}

export async function fetchRecentTasks(
  limit = 20,
  clientId?: string
): Promise<Assignment[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (clientId) {
    query.set("client_id", clientId);
  }
  return requestJson<Assignment[]>(`/api/v1/tasks/recent?${query.toString()}`);
}

export async function switchScheduler(
  scheduler: SchedulerName
): Promise<{ status: string; active_scheduler: string }> {
  return requestJson("/api/v1/control/scheduler", {
    method: "POST",
    body: JSON.stringify({ scheduler }),
  });
}

export async function updateTrafficControl(payload: {
  lambda_rate?: number;
  paused?: boolean;
  spike_tasks?: number;
  spike_client_id?: string;
  spike_task_type?: TaskType;
}): Promise<{
  status: string;
  configured_lambda: number;
  paused: boolean;
  injected_spike_tasks: number;
  queue_depth: number;
}> {
  return requestJson("/api/v1/control/traffic", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function killWorker(workerId: string): Promise<{ status: string }> {
  return requestJson(`/api/v1/control/workers/${encodeURIComponent(workerId)}/kill`, {
    method: "POST",
  });
}

export async function reviveWorker(workerId: string): Promise<{ status: string }> {
  return requestJson(`/api/v1/control/workers/${encodeURIComponent(workerId)}/revive`, {
    method: "POST",
  });
}

export async function fetchSnapshotFallback(): Promise<ClusterSnapshot> {
  return requestJson<ClusterSnapshot>("/api/v1/control/snapshot");
}

export async function fetchBenchmarkRuns(): Promise<BenchmarkRun[]> {
  return requestJson<BenchmarkRun[]>("/api/v1/benchmark/runs");
}

export async function runNewBenchmark(
  seed = 42,
  numBatches = 18
): Promise<BenchmarkRun> {
  return requestJson<BenchmarkRun>(
    `/api/v1/benchmark/run?seed=${seed}&num_batches=${numBatches}`,
    { method: "POST" }
  );
}

// --- Shared Contract API Types and Helpers (D1, D2, D3, D4) ---

export interface TaskContractRequest {
  client_id: string;
  task_type: "light" | "heavy" | string;
  size?: number;
  sent_at?: number | string;
  payload?: any;
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
    throw new Error(`Download failed: HTTP ${res.status}`);
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

