import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Cpu,
  Gauge,
  Laptop,
  Layers,
  Radio,
} from "lucide-react";
import type { ConnectionState } from "../hooks/useWebSocket";
import type { ClusterSnapshot } from "../lib/types";

interface HeaderProps {
  snapshot: ClusterSnapshot | null;
  connectionState: ConnectionState;
  isStale: boolean;
  activeTab?: "ops" | "benchmark";
  onTabChange?: (tab: "ops" | "benchmark") => void;
}

const SCHEDULER_LABELS: Record<string, string> = {
  ortools_milp: "OR-Tools MILP",
  round_robin: "Round Robin",
  least_connections: "Least Connections",
};

export const Header: React.FC<HeaderProps> = ({
  snapshot,
  connectionState,
  isStale,
  activeTab = "ops",
  onTabChange,
}) => {
  const location = useLocation();
  const isClientPage = location.pathname.startsWith("/client");

  const statusColor =
    connectionState === "CONNECTED" && !isStale
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
      : connectionState === "RECONNECTING" || isStale
        ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
        : "bg-rose-500/15 text-rose-300 border-rose-500/40";

  const activeSchedulerLabel = snapshot
    ? SCHEDULER_LABELS[snapshot.active_scheduler] || snapshot.active_scheduler
    : "OR-Tools MILP";

  return (
    <header className="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur sticky top-0 z-30">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-4">
        {/* Brand & Nav */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-cyan-500/15 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-tight text-white">
                  CLOUD<span className="text-cyan-400">BALANCE</span>
                </h1>
                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                  v1.0 GCP
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Adaptive Multi-Resource Cloud Load Balancer
              </p>
            </div>
          </div>

          <nav className="flex items-center gap-1.5 bg-slate-900/90 p-1 rounded-lg border border-slate-800">
            <Link
              to="/"
              onClick={() => onTabChange?.("ops")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition ${
                !isClientPage && activeTab === "ops"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              Ops Center
            </Link>
            {!isClientPage && onTabChange && (
              <button
                type="button"
                onClick={() => onTabChange("benchmark")}
                className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition ${
                  activeTab === "benchmark"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <BarChart3 className="w-3.5 h-3.5" />
                Benchmark Lab
              </button>
            )}
            <Link
              to="/client"
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition ${
                isClientPage
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Laptop className="w-3.5 h-3.5" />
              Laptop Client (/client)
            </Link>
          </nav>
        </div>

        {/* Live Telemetry Header Pills */}
        <div className="flex flex-wrap items-center gap-3">
          {isStale && (
            <div
              role="status"
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/40"
            >
              <AlertTriangle className="w-3.5 h-3.5" />
              Stale Telemetry
            </div>
          )}

          <div
            data-testid="connection-pill"
            className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono border ${statusColor}`}
          >
            <Radio className="w-3.5 h-3.5 animate-pulse" />
            <span>{connectionState}</span>
          </div>

          <div className="flex items-center gap-4 bg-slate-900/90 border border-slate-800 rounded-lg px-3.5 py-1.5 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">Scheduler:</span>
              <span
                data-testid="active-scheduler-pill"
                className="font-mono font-semibold text-cyan-300"
              >
                {activeSchedulerLabel}
              </span>
            </div>
            <div className="h-3.5 w-px bg-slate-800" />
            <div className="flex items-center gap-1.5">
              <Gauge className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-400">&Lambda; Total:</span>
              <span className="font-mono font-semibold text-white">
                {snapshot ? snapshot.lambda_total.toFixed(1) : "0.0"} req/s
              </span>
            </div>
            <div className="h-3.5 w-px bg-slate-800" />
            <div className="flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-slate-400">Queue:</span>
              <span className="font-mono font-semibold text-white">
                {snapshot ? snapshot.queue_depth : 0}
              </span>
            </div>
            <div className="h-3.5 w-px bg-slate-800" />
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">Solver:</span>
              <span className="font-mono font-semibold text-cyan-300">
                {snapshot ? snapshot.avg_solver_latency_ms.toFixed(2) : "0.00"} ms
              </span>
            </div>
          </div>
        </div>
      </div>

      {snapshot?.degraded_mode && snapshot.degraded_warning && (
        <div
          role="alert"
          className="bg-amber-500/15 border-t border-amber-500/40 px-6 py-1.5 text-xs text-amber-200 flex items-center justify-center gap-2"
        >
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
          <span>{snapshot.degraded_warning}</span>
        </div>
      )}
    </header>
  );
};

