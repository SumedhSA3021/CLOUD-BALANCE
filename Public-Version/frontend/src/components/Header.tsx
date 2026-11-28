import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Cpu,
  Gauge,
  Layers,
  LogOut,
  Radio,
} from "lucide-react";
import type { ConnectionState } from "../hooks/useWebSocket";
import type { ClusterSnapshot } from "../lib/types";

interface HeaderProps {
  snapshot: ClusterSnapshot | null;
  connectionState: ConnectionState;
  isStale: boolean;
  mode?: "admin" | "client";
  onSignOut?: () => void;
  activeTab?: "ops" | "benchmark";
  onTabChange?: (tab: "ops" | "benchmark") => void;
}

const SCHEDULER_LABELS: Record<string, string> = {
  ortools_milp: "OR-Tools MILP",
  round_robin: "Round Robin",
};

export const Header: React.FC<HeaderProps> = ({
  snapshot,
  connectionState,
  isStale,
  mode = "admin",
  onSignOut,
  activeTab = "ops",
  onTabChange,
}) => {
  const location = useLocation();
  void activeTab;
  void onTabChange;

  const statusColor =
    connectionState === "CONNECTED" && !isStale
      ? "bg-[#DCFCE7] text-[#15803D] border-[#BBF7D0]"
      : connectionState === "RECONNECTING" || isStale
        ? "bg-[#FEF3C7] text-[#B45309] border-[#FDE68A]"
        : "bg-[#FEE2E2] text-[#B91C1C] border-[#FECACA]";

  const activeSchedulerLabel = snapshot
    ? SCHEDULER_LABELS[snapshot.active_scheduler] || snapshot.active_scheduler
    : "OR-Tools MILP";

  return (
    <header className="border-b border-[#E5DFD3] bg-white/95 backdrop-blur sticky top-0 z-30">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-4">
        {/* Brand & Restricted Navigation */}
        <div className="flex flex-wrap items-center gap-5">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-[#E8F3F5] border border-[#B8DCE3] flex items-center justify-center text-[#0F5C6E]">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-semibold tracking-tight text-[#1C1917]">
                  Cloud<span className="text-[#0F5C6E]">Balance</span>
                </h1>
                <span className="text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded bg-[#F3EFE6] text-[#57534E] border border-[#E5DFD3]">
                  {mode === "admin" ? "Admin Console" : "Client Stream"}
                </span>
              </div>
              <p className="text-xs text-[#78716C]">
                Adaptive Multi-Resource Cloud Load Balancer
              </p>
            </div>
          </div>

          {mode === "admin" && (
            <nav
              aria-label="Admin Navigation"
              className="flex items-center gap-1 bg-[#F3EFE6] p-1 rounded-xl border border-[#E5DFD3]"
            >
              <Link
                to="/ops"
                className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                  location.pathname.startsWith("/ops")
                    ? "bg-white text-[#0F5C6E] border border-[#E5DFD3] shadow-xs font-semibold"
                    : "text-[#57534E] hover:text-[#1C1917]"
                }`}
              >
                <Activity className="w-3.5 h-3.5" />
                Ops Center (/ops)
              </Link>
              <Link
                to="/benchmark"
                className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                  location.pathname.startsWith("/benchmark")
                    ? "bg-white text-[#0F5C6E] border border-[#E5DFD3] shadow-xs font-semibold"
                    : "text-[#57534E] hover:text-[#1C1917]"
                }`}
              >
                <BarChart3 className="w-3.5 h-3.5" />
                Benchmark Lab
              </Link>
            </nav>
          )}
        </div>

        {/* Live Telemetry Header Pills & Sign Out */}
        <div className="flex flex-wrap items-center gap-2.5">
          {isStale && (
            <div
              role="status"
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]"
            >
              <AlertTriangle className="w-3.5 h-3.5" />
              Stale Telemetry
            </div>
          )}

          <div
            data-testid="connection-pill"
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-medium border ${statusColor}`}
          >
            <Radio className="w-3.5 h-3.5" />
            <span>{connectionState}</span>
          </div>

          <div className="flex flex-wrap items-center gap-3.5 bg-[#FAF7F2] border border-[#E5DFD3] rounded-xl px-3.5 py-1.5 text-xs tabular-nums">
            <div className="flex items-center gap-1.5">
              <span className="text-[#78716C]">Scheduler:</span>
              <span
                data-testid="active-scheduler-pill"
                className="font-mono font-semibold text-[#0F5C6E]"
              >
                {activeSchedulerLabel}
              </span>
            </div>
            <div className="h-3.5 w-px bg-[#E5DFD3]" />
            <div className="flex items-center gap-1.5">
              <Gauge className="w-3.5 h-3.5 text-[#15803D]" />
              <span className="text-[#78716C]">&Lambda; Total:</span>
              <span className="font-mono font-semibold text-[#1C1917]">
                {snapshot ? snapshot.lambda_total.toFixed(1) : "0.0"} req/s
              </span>
            </div>
            <div className="h-3.5 w-px bg-[#E5DFD3]" />
            <div className="flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-[#B45309]" />
              <span className="text-[#78716C]">Queue:</span>
              <span className="font-mono font-semibold text-[#1C1917]">
                {snapshot ? snapshot.queue_depth : 0}
              </span>
            </div>
            <div className="h-3.5 w-px bg-[#E5DFD3]" />
            <div className="flex items-center gap-1.5">
              <span className="text-[#78716C]">Solver:</span>
              <span className="font-mono font-semibold text-[#0F5C6E]">
                {snapshot ? snapshot.avg_solver_latency_ms.toFixed(2) : "0.00"} ms
              </span>
            </div>
          </div>

          {mode === "admin" && onSignOut && (
            <button
              type="button"
              onClick={onSignOut}
              className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-medium bg-[#FAF7F2] hover:bg-[#FEE2E2] text-[#57534E] hover:text-[#B91C1C] border border-[#D6CFC2] hover:border-[#FECACA] flex items-center gap-1.5 transition-colors"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>Sign Out</span>
            </button>
          )}
        </div>
      </div>

      {snapshot?.degraded_mode && snapshot.degraded_warning && (
        <div
          role="alert"
          className="bg-[#FEF3C7] border-t border-[#FDE68A] px-6 py-1.5 text-xs text-[#92400E] flex items-center justify-center gap-2"
        >
          <AlertTriangle className="w-4 h-4 text-[#B45309] shrink-0" />
          <span>{snapshot.degraded_warning}</span>
        </div>
      )}
    </header>
  );
};
