import React from "react";
import { Cpu, HardDrive, PowerOff, Server } from "lucide-react";
import type { WorkerSnapshotItem, WorkerStatus } from "../lib/types";

interface WorkerCardProps {
  worker: WorkerSnapshotItem;
  onKillWorker?: (workerId: string) => void;
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

export const WorkerCard: React.FC<WorkerCardProps> = ({ worker, onKillWorker }) => {
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

  return (
    <div
      data-testid={`worker-card-${worker.worker_id}`}
      className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-col justify-between gap-4 hover:border-slate-700 transition"
    >
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
      <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400 font-mono">
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
    </div>
  );
};

