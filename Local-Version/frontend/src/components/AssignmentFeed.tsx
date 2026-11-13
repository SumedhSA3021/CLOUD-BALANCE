import React from "react";
import { ArrowRight, CheckCircle2, Clock, ShieldAlert } from "lucide-react";
import type { Assignment, TaskType } from "../lib/types";

interface AssignmentFeedProps {
  assignments: Assignment[];
}

const TASK_BADGE: Record<TaskType, string> = {
  CPU_INTENSIVE: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40",
  MEMORY_INTENSIVE: "bg-purple-500/15 text-purple-300 border-purple-500/40",
  BALANCED_COMPUTE: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  LIGHTWEIGHT_QUERY: "bg-slate-800 text-slate-300 border-slate-700",
};

export const AssignmentFeed: React.FC<AssignmentFeedProps> = ({ assignments }) => {
  return (
    <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">
            Live Micro-Batch Assignment Feed (Newest at top ↓ Oldest)
          </h2>
          <p className="text-xs text-slate-400">
            Real-time chronological log of dispatched tasks and their assigned internal VMs
          </p>
        </div>
        <span className="text-xs font-mono text-slate-400">
          Showing {assignments.length} recent
        </span>
      </div>

      {assignments.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-400 border border-dashed border-slate-800 rounded-lg">
          No tasks dispatched yet. Start a stream from <code className="text-cyan-300">/client</code> or inject a burst spike above.
        </div>
      ) : (
        <div className="overflow-x-auto max-h-80">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 font-mono text-[11px] uppercase">
                <th className="py-2 px-2.5">Time</th>
                <th className="py-2 px-2.5">Task ID</th>
                <th className="py-2 px-2.5">Client</th>
                <th className="py-2 px-2.5">Workload</th>
                <th className="py-2 px-2.5">Resource Cost</th>
                <th className="py-2 px-2.5">Target VM</th>
                <th className="py-2 px-2.5">Scheduler</th>
                <th className="py-2 px-2.5">Solver / Queue</th>
                <th className="py-2 px-2.5">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {assignments.slice(0, 20).map((item, idx) => {
                const timeStr = new Date(item.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                });
                return (
                  <tr
                    key={item.task_id}
                    className={`transition ${
                      idx === 0
                        ? "bg-cyan-500/10 hover:bg-cyan-500/15"
                        : "hover:bg-slate-800/40"
                    }`}
                  >
                    <td className="py-2 px-2.5 text-slate-400 text-[11px] whitespace-nowrap">
                      {timeStr}
                    </td>
                    <td className="py-2 px-2.5 text-slate-300">{item.task_id}</td>
                    <td className="py-2 px-2.5 font-semibold text-white">
                      {item.client_id}
                    </td>
                    <td className="py-2 px-2.5">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] border ${
                          TASK_BADGE[item.task_type] || TASK_BADGE.LIGHTWEIGHT_QUERY
                        }`}
                      >
                        {item.task_type}
                      </span>
                    </td>
                    <td className="py-2 px-2.5 text-slate-300">
                      {item.cpu_demand_pct}% CPU / {item.mem_demand_mb} MB
                    </td>
                    <td className="py-2 px-2.5">
                      <span className="inline-flex items-center gap-1 text-cyan-300 font-semibold">
                        <ArrowRight className="w-3 h-3" />
                        {item.assigned_worker_id}
                        {idx === 0 && (
                          <span className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-400/40 animate-pulse">
                            LATEST
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="py-2 px-2.5 text-slate-300">{item.scheduler}</td>
                    <td className="py-2 px-2.5 text-slate-400">
                      <span className="text-cyan-300">
                        {item.solver_latency_ms.toFixed(2)}ms
                      </span>{" "}
                      / {item.queue_wait_ms.toFixed(1)}ms
                    </td>
                    <td className="py-2 px-2.5">
                      {item.degraded ? (
                        <span className="inline-flex items-center gap-1 text-amber-300">
                          <ShieldAlert className="w-3.5 h-3.5" />
                          DEGRADED
                        </span>
                      ) : item.status === "COMPLETED" ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          COMPLETED
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-cyan-300">
                          <Clock className="w-3.5 h-3.5" />
                          {item.status}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

