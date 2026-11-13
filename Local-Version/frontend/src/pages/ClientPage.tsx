import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  Laptop,
  Play,
  Sparkles,
  Square,
} from "lucide-react";
import { Header } from "../components/Header";
import { useWebSocket } from "../hooks/useWebSocket";
import { fetchRecentTasks, submitTask, switchScheduler } from "../lib/api";
import type { Assignment, TaskType } from "../lib/types";

type ClientMixOption = "cpu" | "mem" | "balanced";

const MIX_WEIGHTS: Record<ClientMixOption, [number, number, number, number]> = {
  cpu: [0.65, 0.1, 0.15, 0.1],
  mem: [0.1, 0.65, 0.15, 0.1],
  balanced: [0.25, 0.25, 0.3, 0.2],
};

const TASK_TYPES: TaskType[] = [
  "CPU_INTENSIVE",
  "MEMORY_INTENSIVE",
  "BALANCED_COMPUTE",
  "LIGHTWEIGHT_QUERY",
];

function sampleTaskFromMix(mix: ClientMixOption): TaskType {
  const weights = MIX_WEIGHTS[mix];
  const r = Math.random();
  let cumulative = 0;
  for (let i = 0; i < TASK_TYPES.length; i++) {
    cumulative += weights[i];
    if (r <= cumulative) {
      return TASK_TYPES[i];
    }
  }
  return "BALANCED_COMPUTE";
}

function samplePoissonDelayMs(lambdaRate: number): number {
  const u = Math.min(Math.random(), 1 - 1e-9);
  const dtSec = -Math.log(1 - u) / Math.max(0.2, lambdaRate);
  return Math.max(40, Math.min(4000, Math.round(dtSec * 1000)));
}

function sanitizeClientIdLocal(raw: string): string {
  const cleaned = raw
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return (cleaned || "laptop-alpha").slice(0, 64);
}

export const ClientPage: React.FC = () => {
  const { snapshot, connectionState, isStale, refreshNow } = useWebSocket();

  const [clientId, setClientId] = useState<string>("laptop-alpha");
  const [mix, setMix] = useState<ClientMixOption>("cpu");
  const [lambdaRate, setLambdaRate] = useState<number>(3);
  const [streaming, setStreaming] = useState<boolean>(false);
  const [sentCount, setSentCount] = useState<number>(0);
  const [ownTasks, setOwnTasks] = useState<Assignment[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastActionBanner, setLastActionBanner] = useState<{
    label: string;
    taskType: TaskType;
    taskId?: string;
    timestamp: string;
  } | null>(null);

  const streamingRef = useRef<boolean>(false);
  const lambdaRef = useRef<number>(lambdaRate);
  const mixRef = useRef<ClientMixOption>(mix);
  const clientIdRef = useRef<string>(clientId);
  const timerRef = useRef<number | null>(null);
  const syncTimerRef = useRef<number | null>(null);

  lambdaRef.current = lambdaRate;
  mixRef.current = mix;
  clientIdRef.current = clientId;

  const refreshOwnTasks = useCallback(async () => {
    try {
      const normalized = sanitizeClientIdLocal(clientIdRef.current);
      const list = await fetchRecentTasks(30, normalized);
      setOwnTasks(list);
    } catch {
      // fallback to snapshot filter
    }
  }, []);

  useEffect(() => {
    if (snapshot) {
      const normalized = sanitizeClientIdLocal(clientId);
      const filtered = snapshot.recent_assignments.filter(
        (a) => a.client_id === normalized
      );
      if (filtered.length > 0) {
        setOwnTasks(filtered);
      }
    }
  }, [snapshot, clientId]);

  const scheduleDelayedSync = useCallback(() => {
    if (syncTimerRef.current !== null) {
      return;
    }
    syncTimerRef.current = window.setTimeout(() => {
      syncTimerRef.current = null;
      void refreshOwnTasks();
      if (connectionState !== "CONNECTED") {
        void refreshNow();
      }
    }, 350);
  }, [connectionState, refreshNow, refreshOwnTasks]);

  const sendSingleTask = useCallback(
    async (explicitType?: TaskType, actionLabel?: string) => {
      const cid = sanitizeClientIdLocal(clientIdRef.current);
      const tType = explicitType ?? sampleTaskFromMix(mixRef.current);
      try {
        setLastError(null);
        const res = await submitTask(cid, tType);
        const taskId =
          typeof res.task_id === "string" ? res.task_id : undefined;
        setLastActionBanner({
          label: actionLabel || `Auto-Dispatched ${tType}`,
          taskType: tType,
          taskId,
          timestamp: new Date().toLocaleTimeString(),
        });
        setSentCount((c) => c + 1);
        scheduleDelayedSync();
      } catch (err) {
        setLastError(
          err instanceof Error ? err.message : "Task submission failed"
        );
      }
    },
    [scheduleDelayedSync]
  );

  useEffect(() => {
    if (!streaming) {
      streamingRef.current = false;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      return;
    }

    streamingRef.current = true;

    const scheduleNext = () => {
      if (!streamingRef.current) return;
      const delayMs = samplePoissonDelayMs(lambdaRef.current);
      timerRef.current = window.setTimeout(async () => {
        if (!streamingRef.current) return;
        const autoType = sampleTaskFromMix(mixRef.current);
        await sendSingleTask(autoType, "Auto-Stream Request");
        scheduleNext();
      }, delayMs);
    };

    scheduleNext();

    return () => {
      streamingRef.current = false;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [streaming, sendSingleTask]);

  const normalizedClientId = sanitizeClientIdLocal(clientId);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <Header
        snapshot={snapshot}
        connectionState={connectionState}
        isStale={isStale}
      />

      <main className="flex-1 max-w-4xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        {/* Top Identity & Routing Status Bar */}
        <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300">
                <Laptop className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-white">
                  CloudBalance Client Portal
                </h2>
                <p className="text-xs text-slate-400">
                  Single entry point for client devices. Tasks are generated and dispatched automatically and randomly.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                <span className="text-slate-400">Client ID:</span>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  className="bg-transparent text-cyan-300 font-bold w-28 focus:outline-none focus:underline"
                  placeholder="laptop-alpha"
                />
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                Total Sent:{" "}
                <span className="text-emerald-400 font-bold">{sentCount}</span>
              </div>
            </div>
          </div>

          {lastError && (
            <div
              role="alert"
              className="p-3 rounded-lg bg-rose-500/15 border border-rose-500/40 text-xs text-rose-200"
            >
              {lastError}
            </div>
          )}

          {lastActionBanner && (
            <div className="p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <Sparkles className="w-4 h-4 text-cyan-400 shrink-0" />
                <span className="text-slate-200">
                  {lastActionBanner.label}
                </span>
                <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 font-mono text-cyan-300">
                  {lastActionBanner.taskType}
                </span>
                {lastActionBanner.taskId && (
                  <span className="font-mono text-slate-400">
                    ({lastActionBanner.taskId})
                  </span>
                )}
                {ownTasks.length > 0 && (
                  <span className="px-2 py-0.5 rounded bg-cyan-500/20 border border-cyan-400/40 font-mono text-cyan-200 font-semibold flex items-center gap-1">
                    <ArrowRight className="w-3 h-3 text-cyan-400" />
                    Routed to: {ownTasks[0].assigned_worker_id} (
                    {ownTasks[0].scheduler})
                  </span>
                )}
              </div>
              <span className="font-mono text-slate-400">
                {lastActionBanner.timestamp}
              </span>
            </div>
          )}
        </section>

        {/* Workload Stream Generator (Poisson Arrival) Card */}
        <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-6 shadow-lg space-y-6">
          <div className="border-b border-slate-800 pb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-purple-400" />
              <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                Workload Stream Generator (/client) — Automated Poisson Stream
              </h2>
            </div>
            <span className="text-xs font-mono text-slate-400">
              Tasks generated automatically &amp; randomly
            </span>
          </div>

          <div className="p-5 rounded-xl bg-slate-950/60 border border-slate-800/90 space-y-5">
            {/* Active Scheduler Selector */}
            <div className="space-y-2 border-b border-slate-800/80 pb-4">
              <div className="flex items-center justify-between text-xs">
                <label className="font-medium text-slate-300">
                  Active Cluster Scheduler (Controls Routing Algorithm)
                </label>
                <span className="font-mono text-cyan-300 font-semibold text-[11px]">
                  Current: {snapshot?.active_scheduler ?? "ortools_milp"}
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                {[
                  {
                    id: "round_robin" as const,
                    label: "Round Robin",
                    desc: "Strict w1 ➔ w2 ➔ w3 cyclic",
                  },
                  {
                    id: "least_connections" as const,
                    label: "Least Connections",
                    desc: "Fewest active tasks first",
                  },
                  {
                    id: "ortools_milp" as const,
                    label: "OR-Tools MILP",
                    desc: "Adaptive peak CPU balance",
                  },
                ].map((s) => {
                  const isActive =
                    (snapshot?.active_scheduler ?? "ortools_milp") === s.id;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={async () => {
                        try {
                          await switchScheduler(s.id);
                          await refreshNow();
                        } catch (err) {
                          setLastError(
                            err instanceof Error
                              ? err.message
                              : "Failed to switch scheduler"
                          );
                        }
                      }}
                      className={`p-2.5 rounded-lg text-left border transition ${
                        isActive
                          ? s.id === "round_robin"
                            ? "bg-cyan-500/20 border-cyan-400 text-cyan-200 ring-1 ring-cyan-400/50 shadow-sm shadow-cyan-500/20"
                            : s.id === "least_connections"
                              ? "bg-emerald-500/20 border-emerald-400 text-emerald-200 ring-1 ring-emerald-400/50 shadow-sm shadow-emerald-500/20"
                              : "bg-purple-500/20 border-purple-400 text-purple-200 ring-1 ring-purple-400/50 shadow-sm shadow-purple-500/20"
                          : "bg-slate-900/90 border-slate-800 text-slate-400 hover:border-slate-700"
                      }`}
                    >
                      <div className="text-xs font-bold font-mono text-white flex items-center justify-between">
                        <span>{s.label}</span>
                        {isActive && (
                          <span className="text-[10px] text-cyan-300 font-normal">
                            ● ACTIVE
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        {s.desc}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div className="space-y-2">
                <label
                  htmlFor="stream-mix-select"
                  className="block text-xs font-medium text-slate-300"
                >
                  Workload Mix Profile
                </label>
                <select
                  id="stream-mix-select"
                  value={mix}
                  onChange={(e) => setMix(e.target.value as ClientMixOption)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500 font-mono"
                >
                  <option value="cpu">CPU Heavy (65% CPU, 15% Balanced, 10% RAM, 10% Query)</option>
                  <option value="mem">RAM Heavy (65% RAM, 15% Balanced, 10% CPU, 10% Query)</option>
                  <option value="balanced">Balanced Dynamic Mix (Equal spread across all 4 profiles)</option>
                </select>
                <p className="text-[11px] text-slate-500">
                  Mix defines the probability distribution; exact resource demands are resolved by the server.
                </p>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <label
                    htmlFor="client-lambda-slider"
                    className="font-medium text-slate-300"
                  >
                    Poisson Arrival Rate (&lambda;)
                  </label>
                  <span className="font-mono font-bold text-purple-300">
                    {lambdaRate} tasks/second
                  </span>
                </div>
                <input
                  id="client-lambda-slider"
                  type="range"
                  min={1}
                  max={15}
                  step={1}
                  value={lambdaRate}
                  onChange={(e) => setLambdaRate(Number(e.target.value))}
                  className="w-full accent-purple-400 cursor-pointer mt-1"
                />
                <p className="text-[11px] text-slate-500">
                  Inter-arrival delay modeled via exponential distribution: <code>dt = -ln(1 - U) / &lambda;</code>
                </p>
              </div>
            </div>

            <div className="pt-2">
              <button
                type="button"
                onClick={() => setStreaming((s) => !s)}
                className={`w-full py-3 rounded-lg text-sm font-bold flex items-center justify-center gap-2 transition shadow-lg ${
                  streaming
                    ? "bg-rose-500 hover:bg-rose-400 text-slate-950 shadow-rose-500/20"
                    : "bg-purple-500 hover:bg-purple-400 text-slate-950 shadow-purple-500/20"
                }`}
              >
                {streaming ? (
                  <>
                    <Square className="w-4 h-4 fill-current" />
                    Stop Stream
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    Start Stream
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        {/* Live List of Own Tasks */}
        <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-6 shadow-lg space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">
                Live Requests Sent by{" "}
                <span className="font-mono text-cyan-300">
                  {normalizedClientId}
                </span>{" "}
                <span className="text-slate-400 font-normal text-xs">(Newest at top ↓ Oldest)</span>
              </h3>
              <p className="text-xs text-slate-400">
                Real-time chronological log of which internal Worker VM served each request
              </p>
            </div>
            <span className="text-xs font-mono text-slate-400">
              {ownTasks.length} recent request(s)
            </span>
          </div>

          {ownTasks.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-400 border border-dashed border-slate-800 rounded-lg">
              No requests recorded for{" "}
              <code className="text-cyan-300">{normalizedClientId}</code> yet.
              Click <strong className="text-purple-400">Start Stream</strong> above to begin generating automatic workloads.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                    <th className="py-2 px-3">Time</th>
                    <th className="py-2 px-3">Task ID</th>
                    <th className="py-2 px-3">Resolved Type</th>
                    <th className="py-2 px-3">Server Profile</th>
                    <th className="py-2 px-3">Assigned Worker</th>
                    <th className="py-2 px-3">Scheduler</th>
                    <th className="py-2 px-3">Exec Time</th>
                    <th className="py-2 px-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {ownTasks.map((t, idx) => {
                    const timeStr = new Date(t.timestamp).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    });
                    return (
                      <tr
                        key={t.task_id}
                        className={`transition ${
                          idx === 0
                            ? "bg-cyan-500/10 hover:bg-cyan-500/15"
                            : "hover:bg-slate-800/40"
                        }`}
                      >
                        <td className="py-2 px-3 text-slate-400 text-[11px] whitespace-nowrap">
                          {timeStr}
                        </td>
                        <td className="py-2 px-3 text-slate-300">{t.task_id}</td>
                        <td className="py-2 px-3 text-white font-semibold">
                          {t.task_type}
                        </td>
                        <td className="py-2 px-3 text-slate-400">
                          {t.cpu_demand_pct}% CPU / {t.mem_demand_mb} MB
                        </td>
                        <td className="py-2 px-3 text-cyan-300 font-semibold">
                          <span className="inline-flex items-center gap-1">
                            <ArrowRight className="w-3 h-3" />
                            {t.assigned_worker_id}
                            {idx === 0 && (
                              <span className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-400/40 animate-pulse">
                                LATEST TARGET
                              </span>
                            )}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-slate-300">{t.scheduler}</td>
                        <td className="py-2 px-3 text-slate-300">
                          {t.execution_ms
                            ? `${t.execution_ms.toFixed(0)} ms`
                            : "..."}
                        </td>
                        <td className="py-2 px-3">
                          {t.status === "COMPLETED" ? (
                            <span className="inline-flex items-center gap-1 text-emerald-400">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              COMPLETED
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-cyan-300">
                              <Clock className="w-3.5 h-3.5" />
                              {t.status}
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
        </section>
      </main>
    </div>
  );
};
