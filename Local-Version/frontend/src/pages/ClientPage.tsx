import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  Laptop,
  Play,
  Search,
  Server,
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

  // Interactive site widget states
  const [searchQuery, setSearchQuery] = useState<string>("Production Auth Logs");
  const [selectedReport, setSelectedReport] = useState<string>(
    "Q4 Revenue & Region Cohort"
  );
  const [selectedAiJob, setSelectedAiJob] = useState<string>(
    "LLaMA-3 70B Tensor Inference"
  );
  const [selectedDataset, setSelectedDataset] = useState<string>(
    "10M-Node Social Graph Index (1 GB)"
  );
  const [taskActionLabels, setTaskActionLabels] = useState<Record<string, string>>(
    {}
  );

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
        if (taskId && actionLabel) {
          setTaskActionLabels((prev) => ({ ...prev, [taskId]: actionLabel }));
        }
        if (actionLabel) {
          setLastActionBanner({
            label: actionLabel,
            taskType: tType,
            taskId,
            timestamp: new Date().toLocaleTimeString(),
          });
        }
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
        await sendSingleTask(undefined, "Auto-Stream Request");
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

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Top Client Identity & Live Cluster Routing Bar */}
        <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300">
                <Laptop className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-white">
                  CloudBalance Interactive Client Portal
                </h2>
                <p className="text-xs text-slate-400">
                  Interact with any cloud service below. Your browser only sends{" "}
                  <code className="text-cyan-300">{`{ client_id, task_type }`}</code>{" "}
                  to the single Controller entry point; OR-Tools MILP routes your request to the optimal internal Worker VM.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                Active Identity:{" "}
                <span className="text-cyan-300 font-bold">
                  {normalizedClientId}
                </span>
              </div>
              <div className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                Requests Sent:{" "}
                <span className="text-emerald-400 font-bold">{sentCount}</span>
              </div>
            </div>
          </div>

          {/* Quick Identity Switcher + Served-By Worker Distribution */}
          <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t border-slate-800/80">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-400 mr-1">
                Select Device ID:
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
                  Triggered <strong>{lastActionBanner.label}</strong>
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

        {/* Interactive Cloud Application Modules (4 Real User Interactions) */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* 1. Lightweight Query — Search & DB Lookup */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg flex flex-col justify-between space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-lg bg-sky-500/15 border border-sky-500/30 text-sky-300">
                    <Search className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">
                      1. Cloud Search & Instant DB Lookup
                    </h3>
                    <p className="text-[11px] text-slate-400">
                      Fast indexed lookup · Resolves to{" "}
                      <code className="text-sky-300">LIGHTWEIGHT_QUERY</code>{" "}
                      (10% CPU · 128 MB RAM)
                    </p>
                  </div>
                </div>
              </div>

              <div className="pt-2 space-y-2">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search logs, users, or records..."
                    className="flex-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-sky-500"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      void sendSingleTask(
                        "LIGHTWEIGHT_QUERY",
                        `DB Search: "${searchQuery || "All Records"}"`
                      )
                    }
                    className="px-3.5 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs transition shrink-0"
                  >
                    Run Query
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {[
                    "User Session Lookup",
                    "Product Inventory",
                    "API Latency P95",
                  ].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => {
                        setSearchQuery(preset);
                        void sendSingleTask(
                          "LIGHTWEIGHT_QUERY",
                          `Quick Query: "${preset}"`
                        );
                      }}
                      className="px-2 py-0.5 rounded bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 text-[11px] transition"
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* 2. Balanced Compute — Analytics Report Compiler */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg flex flex-col justify-between space-y-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300">
                  <BarChart3 className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">
                    2. Analytics Report & Chart Compiler
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Multi-table aggregation · Resolves to{" "}
                    <code className="text-emerald-300">BALANCED_COMPUTE</code>{" "}
                    (25% CPU · 512 MB RAM)
                  </p>
                </div>
              </div>

              <div className="pt-2 flex gap-2">
                <select
                  value={selectedReport}
                  onChange={(e) => setSelectedReport(e.target.value)}
                  className="flex-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-emerald-500"
                >
                  <option value="Q4 Revenue & Region Cohort">
                    Q4 Revenue & Region Cohort
                  </option>
                  <option value="Real-Time Traffic Anomaly Audit">
                    Real-Time Traffic Anomaly Audit
                  </option>
                  <option value="Cluster SLA & Latency Percentile Report">
                    Cluster SLA & Latency Percentile Report
                  </option>
                </select>
                <button
                  type="button"
                  onClick={() =>
                    void sendSingleTask(
                      "BALANCED_COMPUTE",
                      `Compile Report: ${selectedReport}`
                    )
                  }
                  className="px-3.5 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs transition shrink-0"
                >
                  Compile Report
                </button>
              </div>
            </div>
          </div>

          {/* 3. CPU Intensive — AI Inference & 4K Render Studio */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg flex flex-col justify-between space-y-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300">
                  <Cpu className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">
                    3. Neural AI Inference & 4K Render Studio
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Heavy matrix compute · Resolves to{" "}
                    <code className="text-amber-300">CPU_INTENSIVE</code> (35%
                    CPU · 256 MB RAM)
                  </p>
                </div>
              </div>

              <div className="pt-2 flex gap-2">
                <select
                  value={selectedAiJob}
                  onChange={(e) => setSelectedAiJob(e.target.value)}
                  className="flex-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-amber-500"
                >
                  <option value="LLaMA-3 70B Tensor Inference">
                    LLaMA-3 70B Tensor Inference
                  </option>
                  <option value="4K Raytraced Frame Pass (2400x2400)">
                    4K Raytraced Frame Pass (2400x2400)
                  </option>
                  <option value="Deep ResNet-152 Image Batch">
                    Deep ResNet-152 Image Batch
                  </option>
                </select>
                <button
                  type="button"
                  onClick={() =>
                    void sendSingleTask(
                      "CPU_INTENSIVE",
                      `AI Compute: ${selectedAiJob}`
                    )
                  }
                  className="px-3.5 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs transition shrink-0"
                >
                  Run AI Job
                </button>
              </div>
            </div>
          </div>

          {/* 4. Memory Intensive — In-Memory Big Data Graph Loader */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg flex flex-col justify-between space-y-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-purple-500/15 border border-purple-500/30 text-purple-300">
                  <Database className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">
                    4. In-Memory Big Data Graph Engine
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    High RAM allocation · Resolves to{" "}
                    <code className="text-purple-300">MEMORY_INTENSIVE</code>{" "}
                    (15% CPU · 1024 MB RAM)
                  </p>
                </div>
              </div>

              <div className="pt-2 flex gap-2">
                <select
                  value={selectedDataset}
                  onChange={(e) => setSelectedDataset(e.target.value)}
                  className="flex-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                >
                  <option value="10M-Node Social Graph Index (1 GB)">
                    10M-Node Social Graph Index (1 GB)
                  </option>
                  <option value="Genomic Sequence Alignment Matrix">
                    Genomic Sequence Alignment Matrix
                  </option>
                  <option value="In-Memory Fraud Tensor Cube">
                    In-Memory Fraud Tensor Cube
                  </option>
                </select>
                <button
                  type="button"
                  onClick={() =>
                    void sendSingleTask(
                      "MEMORY_INTENSIVE",
                      `RAM Graph Load: ${selectedDataset}`
                    )
                  }
                  className="px-3.5 py-1.5 rounded-lg bg-purple-500 hover:bg-purple-400 text-slate-950 font-bold text-xs transition shrink-0"
                >
                  Load into RAM
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Live Internal Worker VMs Strip (Real-Time Feedback on Client Page) */}
        {snapshot && snapshot.workers.length > 0 && (
          <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-cyan-400" />
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  Live Internal Worker VMs (Real-Time Load Balancing View)
                </h3>
              </div>
              <span className="text-[11px] font-mono text-slate-400">
                Active Scheduler:{" "}
                <strong className="text-cyan-300">
                  {snapshot.active_scheduler}
                </strong>
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {snapshot.workers.map((w) => (
                <div
                  key={w.worker_id}
                  className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-2"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono font-bold text-white">
                      {w.worker_id}{" "}
                      <span className="text-[10px] text-slate-500 font-normal">
                        ({w.ip_address}:{w.port})
                      </span>
                    </span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                        w.status === "CRITICAL"
                          ? "bg-rose-500/20 text-rose-300"
                          : w.status === "MODERATE"
                          ? "bg-amber-500/20 text-amber-300"
                          : "bg-emerald-500/20 text-emerald-300"
                      }`}
                    >
                      {w.status}
                    </span>
                  </div>
                  <div className="space-y-1 text-[11px] font-mono">
                    <div className="flex justify-between">
                      <span className="text-slate-400">CPU</span>
                      <span className="text-cyan-300">
                        {w.cpu_percent.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full transition-all duration-300 ${
                          w.cpu_percent >= 85
                            ? "bg-rose-500"
                            : w.cpu_percent >= 60
                            ? "bg-amber-400"
                            : "bg-cyan-400"
                        }`}
                        style={{ width: `${Math.min(100, w.cpu_percent)}%` }}
                      />
                    </div>
                    <div className="flex justify-between pt-1">
                      <span className="text-slate-400">RAM</span>
                      <span className="text-purple-300">
                        {Math.round(w.memory_used_mb)} /{" "}
                        {Math.round(w.memory_total_mb)} MB (
                        {w.memory_percent.toFixed(1)}%)
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-400 transition-all duration-300"
                        style={{ width: `${Math.min(100, w.memory_percent)}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Automated Poisson Stream Generator Card (Preserved for Stress Testing) */}
        <section className="rounded-xl bg-slate-900/90 border border-slate-800 p-6 shadow-lg space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300">
                <Activity className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-white">
                  Laptop Client Workload Generator (/client) — Automated Poisson Stream
                </h2>
                <p className="text-xs text-slate-400">
                  Optional continuous Poisson request stream (
                  <code>dt = -ln(1 - U) / &lambda;</code>) for hands-free load testing.
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Client ID Input */}
            <div className="space-y-1.5">
              <label
                htmlFor="client-id-input"
                className="block text-xs font-medium text-slate-300"
              >
                Client Laptop Identifier
              </label>
              <input
                id="client-id-input"
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="e.g. laptop-alpha"
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm font-mono text-white focus:outline-none focus:border-cyan-500"
              />
            </div>

            {/* Workload Mix Selector */}
            <div className="space-y-1.5">
              <label
                htmlFor="workload-mix-select"
                className="block text-xs font-medium text-slate-300"
              >
                Workload Resource Mix
              </label>
              <select
                id="workload-mix-select"
                value={mix}
                onChange={(e) => setMix(e.target.value as ClientMixOption)}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-sm text-white focus:outline-none focus:border-cyan-500"
              >
                <option value="cpu">CPU Heavy (65% CPU_INTENSIVE)</option>
                <option value="mem">Memory Heavy (65% MEMORY_INTENSIVE)</option>
                <option value="balanced">Balanced Mix (All 4 Profiles)</option>
              </select>
            </div>

            {/* Poisson Lambda Slider */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <label
                  htmlFor="client-lambda-slider"
                  className="font-medium text-slate-300"
                >
                  Poisson Arrival Rate (&lambda;)
                </label>
                <span className="font-mono font-bold text-cyan-300">
                  {lambdaRate} tasks/s
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
                className="w-full accent-cyan-400 cursor-pointer mt-2"
              />
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button
              type="button"
              onClick={() => setStreaming((s) => !s)}
              className={`px-5 py-2.5 rounded-lg text-xs font-bold flex items-center gap-2 transition ${
                streaming
                  ? "bg-rose-500 hover:bg-rose-400 text-slate-950"
                  : "bg-cyan-500 hover:bg-cyan-400 text-slate-950"
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

            <button
              type="button"
              onClick={() =>
                void sendSingleTask(
                  "CPU_INTENSIVE",
                  "Manual Heavy Matrix Task"
                )
              }
              className="px-4 py-2.5 rounded-lg text-xs font-semibold bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 flex items-center gap-2 transition"
            >
              <Zap className="w-4 h-4 text-amber-400" />
              Send one heavy task
            </button>
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
                Real-time visibility into which internal Worker VM served each
                interaction from this device
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
              Click any interactive service card above (`Run Query`,{" "}
              `Compile Report`, `Run AI Job`, `Load into RAM`).
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                    <th className="py-2 px-3">Task ID</th>
                    <th className="py-2 px-3">Interaction / Task Type</th>
                    <th className="py-2 px-3">Server Profile</th>
                    <th className="py-2 px-3">Assigned Internal VM</th>
                    <th className="py-2 px-3">Scheduler</th>
                    <th className="py-2 px-3">Exec Time</th>
                    <th className="py-2 px-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {ownTasks.map((t) => (
                    <tr key={t.task_id} className="hover:bg-slate-800/40">
                      <td className="py-2 px-3 text-slate-300">{t.task_id}</td>
                      <td className="py-2 px-3">
                        <div className="text-white font-semibold">
                          {t.task_type}
                        </div>
                        {taskActionLabels[t.task_id] && (
                          <div className="text-[10px] text-slate-400 font-sans">
                            {taskActionLabels[t.task_id]}
                          </div>
                        )}
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
