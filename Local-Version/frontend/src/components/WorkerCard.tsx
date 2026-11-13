import React from "react";
import { Cpu, HardDrive, PowerOff, Server } from "lucide-react";
import type { WorkerSnapshotItem, WorkerStatus } from "../lib/types";

interface WorkerCardProps {
  worker: WorkerSnapshotItem;
  onKillWorker?: (workerId: string) => void;
  isLatestTarget?: boolean;
  activeScheduler?: string;
  latestTaskId?: string;
  latestTaskType?: string;
}

const STATUS_BADGE: Record<WorkerStatus, string> = {
  HEALTHY: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  MODERATE: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  CRITICAL: "bg-rose-500/20 text-rose-300 border-rose-500/50 animate-pulse",
};

const BAR_COLOR: Record<WorkerStatus, string> = {
  HEALTHY: "bg-emerald-500",
  MODERATE: "bg-amber-500",
  CRITICAL: "bg-rose-500",
};

export const WorkerCard: React.FC<WorkerCardProps> = ({
  worker,
  onKillWorker,
  isLatestTarget = false,
  activeScheduler = "ortools_milp",
  latestTaskId,
  latestTaskType,
}) => {
  const cpuStatus: WorkerStatus =
    worker.cpu_percent >= 85
      ? "CRITICAL"
      : worker.cpu_percent >= 60
        ? "MODERATE"
        : "HEALTHY";

  const memStatus: WorkerStatus =
    worker.memory_percent >= 90
      ? "CRITICAL"
      : worker.memory_percent >= 70
        ? "MODERATE"
        : "HEALTHY";

  // Dynamic styling when this worker is the latest to receive load
  const isRoundRobin = activeScheduler === "round_robin";
  const isLeastConn = activeScheduler === "least_connections";

  let containerHighlightClass =
    "border-slate-800 bg-slate-900/90 hover:border-slate-700";
  if (isLatestTarget) {
    if (isRoundRobin) {
      containerHighlightClass =
        "border-cyan-400 ring-2 ring-cyan-400/80 shadow-[0_0_25px_rgba(34,211,238,0.25)] bg-gradient-to-b from-cyan-950/30 via-slate-900/95 to-slate-900/95";
    } else if (isLeastConn) {
      containerHighlightClass =
        "border-emerald-400 ring-2 ring-emerald-400/80 shadow-[0_0_25px_rgba(16,185,129,0.25)] bg-gradient-to-b from-emerald-950/30 via-slate-900/95 to-slate-900/95";
    } else {
      containerHighlightClass =
        "border-purple-400 ring-2 ring-purple-400/80 shadow-[0_0_25px_rgba(168,85,247,0.25)] bg-gradient-to-b from-purple-950/30 via-slate-900/95 to-slate-900/95";
    }
  }

  return (
    <div
      data-testid={`worker-card-${worker.worker_id}`}
      className={`rounded-xl border p-4 shadow-lg flex flex-col justify-between gap-4 transition duration-200 ${containerHighlightClass}`}
    >
      {/* Top Banner when Worker Just Received Load */}
      {isLatestTarget && (
        <div
          data-testid={`worker-assigned-banner-${worker.worker_id}`}
          className={`flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono border ${
            isRoundRobin
              ? "bg-cyan-500/20 border-cyan-400/50 text-cyan-300"
              : isLeastConn
                ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-300"
                : "bg-purple-500/20 border-purple-400/50 text-purple-300"
          }`}
        >
          <div className="flex items-center gap-1.5 font-bold">
            <span className="relative flex h-2 w-2">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  isRoundRobin
                    ? "bg-cyan-400"
                    : isLeastConn
                      ? "bg-emerald-400"
                      : "bg-purple-400"
                }`}
              />
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  isRoundRobin
                    ? "bg-cyan-400"
                    : isLeastConn
                      ? "bg-emerald-400"
                      : "bg-purple-400"
                }`}
              />
            </span>
            <span>
              {isRoundRobin
                ? "LOAD RECEIVED (Round Robin)"
                : isLeastConn
                  ? "LOAD RECEIVED (Least Connections)"
                  : "LOAD RECEIVED (MILP Minimax)"}
            </span>
          </div>
          <span className="text-[10px] uppercase tracking-wide opacity-90">
            {isRoundRobin
              ? "Cyclic Pointer Turn"
              : isLeastConn
                ? `Min Active (${worker.active_tasks} Tasks)`
                : "Optimal Placement"}
          </span>
        </div>
      )}

      {/* Top Row: ID + Status Pill */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-slate-800 text-cyan-400 border border-slate-700">
            <Server className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold font-mono text-white">
              {worker.worker_id}
            </h3>
            <p className="text-[11px] font-mono text-slate-400">
              {worker.ip_address}:{worker.port} (internal)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            data-testid={`worker-status-${worker.worker_id}`}
            className={`px-2.5 py-0.5 rounded-full text-[11px] font-mono font-semibold border ${STATUS_BADGE[worker.status]}`}
          >
            {worker.status}
          </span>
          {onKillWorker && (
            <button
              type="button"
              title={`Simulate failure on ${worker.worker_id}`}
              onClick={() => onKillWorker(worker.worker_id)}
              className="p-1.5 rounded-md bg-rose-500/10 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 transition"
            >
              <PowerOff className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* CPU Utilization Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-slate-300">
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            CPU Load
          </span>
          <span className="font-mono font-semibold text-white">
            {worker.cpu_percent.toFixed(1)}%{" "}
            <span className="text-[10px] text-slate-400">(cap 85%)</span>
          </span>
        </div>
        <div className="relative h-2.5 w-full rounded-full bg-slate-800 overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${BAR_COLOR[cpuStatus]}`}
            style={{ width: `${Math.min(100, Math.max(0, worker.cpu_percent))}%` }}
          />
          {/* 85% MILP Cap Marker */}
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-rose-400/80"
            style={{ left: "85%" }}
            title="85% MILP CPU Safety Cap"
          />
        </div>
      </div>

      {/* RAM Utilization Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-slate-300">
            <HardDrive className="w-3.5 h-3.5 text-purple-400" />
            Memory
          </span>
          <span className="font-mono text-white">
            <span className="font-semibold">{Math.round(worker.memory_used_mb)}</span>
            <span className="text-slate-400">
              {" "}
              / {Math.round(worker.memory_total_mb)} MB ({worker.memory_percent.toFixed(1)}%)
            </span>
          </span>
        </div>
        <div className="relative h-2.5 w-full rounded-full bg-slate-800 overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${BAR_COLOR[memStatus]}`}
            style={{ width: `${Math.min(100, Math.max(0, worker.memory_percent))}%` }}
          />
          {/* 90% MILP Cap Marker */}
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-rose-400/80"
            style={{ left: "90%" }}
            title="90% MILP RAM Safety Cap"
          />
        </div>
      </div>

      {/* Bottom Stats Footer */}
      <div className="pt-2 border-t border-slate-800/80 space-y-1.5 font-mono text-xs">
        <div className="flex items-center justify-between text-slate-400">
          <div>
            Active Tasks:{" "}
            <span className="text-cyan-300 font-semibold">{worker.active_tasks}</span>
          </div>
          <div>
            Load 1m:{" "}
            <span className="text-slate-200">{worker.load_avg_1m.toFixed(2)}</span>
          </div>
          <div>
            In-Flight:{" "}
            <span className="text-amber-300">
              +{worker.in_flight_cpu_pct.toFixed(0)}% CPU
            </span>
          </div>
        </div>
        {isLatestTarget && latestTaskId && (
          <div className="flex items-center justify-between text-[11px] pt-1 border-t border-slate-800/40 text-slate-400">
            <span className="text-slate-500">Most Recent Load:</span>
            <span className="text-cyan-300 font-semibold">
              {latestTaskId} {latestTaskType ? `(${latestTaskType})` : ""}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

