import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  Laptop,
  Play,
  Send,
  Sparkles,
  Square,
  Zap,
} from "lucide-react";
import { Header } from "../components/Header";
import { useWebSocket } from "../hooks/useWebSocket";
import { fetchRecentTasks, submitTask } from "../lib/api";
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

const PRESET_CLIENTS: { id: string; mix: ClientMixOption; label: string }[] = [
  { id: "laptop-alpha", mix: "cpu", label: "laptop-alpha (CPU)" },
  { id: "laptop-beta", mix: "mem", label: "laptop-beta (RAM)" },
  { id: "laptop-gamma", mix: "balanced", label: "laptop-gamma (Mix)" },
  { id: "mobile-1", mix: "cpu", label: "mobile-1" },
  { id: "mobile-2", mix: "mem", label: "mobile-2" },
];

export const ClientPage: React.FC = () => {
  const { snapshot, connectionState, isStale, refreshNow } = useWebSocket();

  const [clientId, setClientId] = useState<string>("laptop-alpha");
  const [selectedTaskType, setSelectedTaskType] = useState<TaskType>("CPU_INTENSIVE");
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
      const tType = explicitType ?? selectedTaskType;
      try {
        setLastError(null);
        const res = await submitTask(cid, tType);
        const taskId =
          typeof res.task_id === "string" ? res.task_id : undefined;
        setLastActionBanner({
          label: actionLabel || `Sent ${tType}`,
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
    [selectedTaskType, scheduleDelayedSync]
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
  const myClientStats = snapshot?.clients.find(
    (c) => c.client_id === normalizedClientId
  );

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <Header
        snapshot={snapshot}
        connectionState={connectionState}
        isStale={isStale}
      />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
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
                  Single entry point for client devices. Submit individual tasks or stream Poisson workloads to the Controller.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                Active Client ID:{" "}
                <span className="text-cyan-300 font-bold">
                  {normalizedClientId}
                </span>
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                Total Sent:{" "}
                <span className="text-emerald-400 font-bold">{sentCount}</span>
              </div>
            </div>
          </div>

          {/* Quick Preset Selector */}
          <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-slate-800/80">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-400 mr-1">
                Preset Devices:
              </span>
              {PRESET_CLIENTS.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => {
                    setClientId(preset.id);
                    setMix(preset.mix);
                  }}
                  className={`px-2.5 py-1 rounded-md text-xs font-mono border transition ${
                    normalizedClientId === preset.id
                      ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/50 font-semibold"
                      : "bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            {myClientStats && Object.keys(myClientStats.served_by).length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                <span className="text-slate-400">Served by VMs:</span>
                {Object.entries(myClientStats.served_by).map(([wid, count]) => (
                  <span
                    key={wid}
                    className="px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-300"
                  >
                    {wid}: {count}
                  </span>
                ))}
              </div>
            )}
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
              <div className="flex items-center gap-2">
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
              </div>
              <span className="font-mono text-slate-400">
                {lastActionBanner.timestamp}
              </span>
            </div>
          )}
        </section>

        {/* Core Controls Card: Send Task & Stream Options */}
        <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-6 shadow-lg space-y-6">
          <div className="border-b border-slate-800 pb-3 flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Laptop Client Workload Generator (/client)
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* OPTION 1: SEND TASK */}
            <div className="p-5 rounded-xl bg-slate-950/60 border border-slate-800/90 space-y-4">
              <div className="flex items-center gap-2 text-cyan-300 border-b border-slate-800 pb-2">
                <Send className="w-4 h-4" />
                <h3 className="text-xs font-bold uppercase tracking-wider">
                  Option 1: Send Single Task
                </h3>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="task-type-select"
                  className="block text-xs font-medium text-slate-300"
                >
                  Select Task Type
                </label>
                <select
                  id="task-type-select"
                  value={selectedTaskType}
                  onChange={(e) => setSelectedTaskType(e.target.value as TaskType)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
                >
                  <option value="CPU_INTENSIVE">
                    CPU_INTENSIVE (35% CPU · 256 MB RAM)
                  </option>
                  <option value="MEMORY_INTENSIVE">
                    MEMORY_INTENSIVE (15% CPU · 1024 MB RAM)
                  </option>
                  <option value="BALANCED_COMPUTE">
                    BALANCED_COMPUTE (25% CPU · 512 MB RAM)
                  </option>
                  <option value="LIGHTWEIGHT_QUERY">
                    LIGHTWEIGHT_QUERY (10% CPU · 128 MB RAM)
                  </option>
                </select>
              </div>

              <div className="flex flex-wrap gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => void sendSingleTask(selectedTaskType, "Manual Single Task")}
                  className="flex-1 px-4 py-2.5 rounded-lg text-xs font-bold bg-cyan-500 hover:bg-cyan-400 text-slate-950 flex items-center justify-center gap-2 transition shadow-lg shadow-cyan-500/10"
                >
                  <Send className="w-4 h-4" />
                  Send Task
                </button>

                <button
                  type="button"
                  onClick={() =>
                    void sendSingleTask("CPU_INTENSIVE", "Manual Heavy Matrix Task")
                  }
                  className="px-4 py-2.5 rounded-lg text-xs font-semibold bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 flex items-center gap-2 transition"
                >
                  <Zap className="w-4 h-4 text-amber-400" />
                  Send one heavy task
                </button>
              </div>
            </div>

            {/* OPTION 2: STREAM OPTIONS */}
            <div className="p-5 rounded-xl bg-slate-950/60 border border-slate-800/90 space-y-4">
              <div className="flex items-center gap-2 text-purple-300 border-b border-slate-800 pb-2">
                <Activity className="w-4 h-4" />
                <h3 className="text-xs font-bold uppercase tracking-wider">
                  Option 2: Stream Options (Poisson Arrival)
                </h3>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label
                    htmlFor="stream-mix-select"
                    className="block text-xs font-medium text-slate-300"
                  >
                    Stream Mix Profile
                  </label>
                  <select
                    id="stream-mix-select"
                    value={mix}
                    onChange={(e) => setMix(e.target.value as ClientMixOption)}
                    className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500 font-mono"
                  >
                    <option value="cpu">CPU Heavy (65%)</option>
                    <option value="mem">RAM Heavy (65%)</option>
                    <option value="balanced">Balanced (Mix)</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <label
                      htmlFor="client-lambda-slider"
                      className="font-medium text-slate-300"
                    >
                      Rate (&lambda;)
                    </label>
                    <span className="font-mono font-bold text-purple-300">
                      {lambdaRate} req/s
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
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => setStreaming((s) => !s)}
                  className={`w-full py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-2 transition shadow-lg ${
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
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Real-time visibility into which internal Worker VM served each request
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
              Click <strong className="text-white">Send Task</strong> or <strong className="text-white">Start Stream</strong> above.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                    <th className="py-2 px-3">Task ID</th>
                    <th className="py-2 px-3">Task Type</th>
                    <th className="py-2 px-3">Server Profile</th>
                    <th className="py-2 px-3">Assigned Worker</th>
                    <th className="py-2 px-3">Scheduler</th>
                    <th className="py-2 px-3">Exec Time</th>
                    <th className="py-2 px-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {ownTasks.map((t) => (
                    <tr key={t.task_id} className="hover:bg-slate-800/40">
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
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
};
