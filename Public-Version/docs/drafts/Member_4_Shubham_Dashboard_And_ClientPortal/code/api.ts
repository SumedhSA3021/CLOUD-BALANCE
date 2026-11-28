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

