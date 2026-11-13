import React, { useState } from "react";
import { AssignmentFeed } from "../components/AssignmentFeed";
import { BenchmarkSection } from "../components/BenchmarkSection";
import { ClientPanel } from "../components/ClientPanel";
import { ControlPanel } from "../components/ControlPanel";
import { Header } from "../components/Header";
import { MetricsChart } from "../components/MetricsChart";
import { WorkerCard } from "../components/WorkerCard";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  killWorker,
  reviveWorker,
  switchScheduler,
  updateTrafficControl,
} from "../lib/api";
import type { SchedulerName } from "../lib/types";

export const DashboardPage: React.FC = () => {
  const { snapshot, history, connectionState, isStale, error, refreshNow } =
    useWebSocket();
  const [activeTab, setActiveTab] = useState<"ops" | "benchmark">("ops");
  const [actionError, setActionError] = useState<string | null>(null);

  const handleSelectScheduler = async (sched: SchedulerName) => {
    try {
      setActionError(null);
      await switchScheduler(sched);
      await refreshNow();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to switch scheduler");
    }
  };

  const handleChangeLambda = async (rate: number) => {
    try {
      setActionError(null);
      await updateTrafficControl({ lambda_rate: rate });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to update lambda");
    }
  };

  const handleTogglePause = async (paused: boolean) => {
    try {
      setActionError(null);
      await updateTrafficControl({ paused });
      await refreshNow();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to toggle pause");
    }
  };

  const handleKillWorker = async (workerId: string) => {
    try {
      setActionError(null);
      await killWorker(workerId);
      await refreshNow();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to kill worker");
    }
  };

  const handleReviveAllWorkers = async () => {
    try {
      setActionError(null);
      for (const wid of ["worker-1", "worker-2", "worker-3"]) {
        await reviveWorker(wid);
      }
      await refreshNow();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to revive workers");
    }
  };

  const workers = snapshot?.workers ?? [];
  const assignments = snapshot?.recent_assignments ?? [];
  const clients = snapshot?.clients ?? [];
  const latestAssignment = assignments.length > 0 ? assignments[0] : null;
  const activeScheduler = snapshot?.active_scheduler ?? "ortools_milp";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <Header
        snapshot={snapshot}
        connectionState={connectionState}
        isStale={isStale}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 py-5 space-y-5">
        {(error || actionError) && (
          <div
            role="alert"
            className="rounded-lg bg-rose-500/15 border border-rose-500/40 px-4 py-2.5 text-xs text-rose-200"
          >
            {actionError || error}
          </div>
        )}

        <ControlPanel
          activeScheduler={snapshot?.active_scheduler ?? "ortools_milp"}
          lambdaTotal={snapshot?.lambda_total ?? 12}
          paused={snapshot?.paused ?? false}
          onSelectScheduler={handleSelectScheduler}
          onChangeLambda={handleChangeLambda}
          onTogglePause={handleTogglePause}
          onReviveAllWorkers={handleReviveAllWorkers}
        />

        {activeTab === "benchmark" ? (
          <BenchmarkSection />
        ) : (
          <>
            {/* Worker VMs Grid */}
            <section aria-label="Internal Worker VMs">
              <div className="flex items-center justify-between mb-2.5">
                <h2 className="text-xs font-mono uppercase tracking-wider text-slate-400">
                  Internal VPC Worker VMs ({workers.length} Active)
                </h2>
                <span className="text-[11px] text-slate-500 font-mono">
                  Redis TTL: 10s | Telemetry Poll: 2.0s
                </span>
              </div>

              {/* Dynamic Scheduler Rotation Indicator */}
              {activeScheduler === "round_robin" && (
                <div
                  data-testid="rr-rotation-flow"
                  className="mb-3.5 p-3 rounded-xl bg-cyan-950/40 border border-cyan-500/40 shadow-sm flex flex-wrap items-center justify-between gap-3 text-xs font-mono"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-300 font-bold uppercase tracking-wider flex items-center gap-1.5">
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400" />
                      </span>
                      Round Robin Rotation Flow:
                    </span>
                    <div className="flex items-center gap-1.5 text-xs">
                      {["worker-1", "worker-2", "worker-3"].map((wid, idx) => {
                        const isCurrentTarget =
                          latestAssignment?.assigned_worker_id === wid;
                        return (
                          <React.Fragment key={wid}>
                            <span
                              className={`px-2.5 py-1 rounded font-bold transition duration-200 ${
                                isCurrentTarget
                                  ? "bg-cyan-500 text-slate-950 ring-2 ring-cyan-300 shadow-md shadow-cyan-500/40 scale-105"
                                  : "bg-slate-900 border border-slate-700 text-slate-400"
                              }`}
                            >
                              {wid}
                            </span>
                            {idx < 2 && (
                              <span className="text-cyan-400 font-bold">➔</span>
                            )}
                          </React.Fragment>
                        );
                      })}
                      <span className="text-cyan-400 font-bold ml-1">➔ (repeats w1)</span>
                    </div>
                  </div>
                  <span className="text-cyan-200 text-[11px]">
                    Current Target:{" "}
                    <strong className="text-white underline font-bold">
                      {latestAssignment?.assigned_worker_id ?? "worker-1"}
                    </strong>
                  </span>
                </div>
              )}

              {activeScheduler === "least_connections" && (
                <div
                  data-testid="lc-priority-flow"
                  className="mb-3.5 p-3 rounded-xl bg-emerald-950/40 border border-emerald-500/40 shadow-sm flex flex-wrap items-center justify-between gap-3 text-xs font-mono"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-300 font-bold uppercase tracking-wider flex items-center gap-1.5">
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
                      </span>
                      Least Connections Routing:
                    </span>
                    <span className="text-slate-300">
                      Dispatches to worker with fewest active tasks (Tie-break: w1 ➔ w2 ➔ w3)
                    </span>
                  </div>
                  <span className="text-emerald-200 text-[11px]">
                    Selected Node:{" "}
                    <strong className="text-white underline font-bold">
                      {latestAssignment?.assigned_worker_id ?? "worker-1"}
                    </strong>
                  </span>
                </div>
              )}

              {workers.length === 0 ? (
                <div className="rounded-xl bg-slate-900/90 border border-dashed border-slate-800 p-8 text-center text-xs text-slate-400">
                  No active worker VMs reporting in Redis (`cluster:worker:*`). Click{" "}
                  <strong className="text-cyan-300">Restore VMs</strong> above to re-seed.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {workers.map((worker) => {
                    const isLatest =
                      latestAssignment?.assigned_worker_id === worker.worker_id;
                    return (
                      <WorkerCard
                        key={worker.worker_id}
                        worker={worker}
                        onKillWorker={(wid) => void handleKillWorker(wid)}
                        isLatestTarget={isLatest}
                        activeScheduler={activeScheduler}
                        latestTaskId={
                          isLatest ? latestAssignment?.task_id : undefined
                        }
                        latestTaskType={
                          isLatest ? latestAssignment?.task_type : undefined
                        }
                      />
                    );
                  })}
                </div>
              )}
            </section>

            {/* Rolling 60-Point Telemetry Chart */}
            <MetricsChart history={history} workers={workers} />

            {/* Per-Client Panel */}
            <ClientPanel clients={clients} />

            {/* Live Assignment Feed */}
            <AssignmentFeed assignments={assignments} />
          </>
        )}
      </main>
    </div>
  );
};

