/** Strict TypeScript data contracts mirroring CloudBalance /api/v1 Pydantic schemas. */

export type TaskType =
  | "CPU_INTENSIVE"
  | "MEMORY_INTENSIVE"
  | "BALANCED_COMPUTE"
  | "LIGHTWEIGHT_QUERY";

export type WorkerStatus = "HEALTHY" | "MODERATE" | "CRITICAL";

export type SchedulerName =
  | "ortools_milp"
  | "round_robin"
  | "least_connections";

export interface WorkerSnapshotItem {
  worker_id: string;
  ip_address: string;
  port: number;
  cpu_percent: number;
  memory_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  active_tasks: number;
  status: WorkerStatus;
  load_avg_1m: number;
  in_flight_cpu_pct: number;
  in_flight_mem_mb: number;
}

export interface Assignment {
  task_id: string;
  client_id: string;
  task_type: TaskType;
  cpu_demand_pct: number;
  mem_demand_mb: number;
  assigned_worker_id: string;
  scheduler: string;
  solver_latency_ms: number;
  queue_wait_ms: number;
  execution_ms: number;
  status: string;
  degraded: boolean;
  timestamp: string;
}

export interface ClientStats {
  client_id: string;
  req_per_sec: number;
  queued: number;
  total_sent: number;
  avg_queue_wait_ms: number;
  served_by: Record<string, number>;
}

export interface ClusterSnapshot {
  type: "CLUSTER_SNAPSHOT";
  timestamp: string;
  workers: WorkerSnapshotItem[];
  recent_assignments: Assignment[];
  clients: ClientStats[];
  queue_depth: number;
  active_scheduler: SchedulerName | string;
  lambda_total: number;
  avg_solver_latency_ms: number;
  degraded_mode: boolean;
  degraded_warning: string | null;
  paused: boolean;
}

export interface TaskSubmissionResponse {
  accepted: boolean;
  task_id: string;
  client_id: string;
  task_type: TaskType;
  cpu_demand_pct: number;
  mem_demand_mb: number;
  duration_sec: number;
  matrix_dim: number;
  queue_depth: number;
  queued_at: string;
}

export interface SchedulerBenchmarkMetrics {
  scheduler: string;
  total_tasks: number;
  completed_tasks: number;
  degraded_assignments: number;
  cpu_stddev_mean: number;
  cpu_stddev_max: number;
  peak_cpu_pct: number;
  peak_mem_pct: number;
  cpu_cap_violations: number;
  mem_cap_violations: number;
  total_cap_violations: number;
  mean_completion_latency_ms: number;
  p95_completion_latency_ms: number;
  mean_solver_latency_ms: number;
  p95_solver_latency_ms: number;
  throughput_tasks_per_sec: number;
  time_series_cpu_stddev: number[];
  time_series_peak_cpu: number[];
  worker_assignment_counts: Record<string, number>;
}

export interface BenchmarkRun {
  run_id: string;
  seed: number;
  total_tasks: number;
  duration_sec: number;
  created_at: string;
  results: Record<string, SchedulerBenchmarkMetrics>;
  markdown_table: string;
}

export interface WorkerHistoryPoint {
  timestampLabel: string;
  cpuByWorker: Record<string, number>;
  memByWorker: Record<string, number>;
}

