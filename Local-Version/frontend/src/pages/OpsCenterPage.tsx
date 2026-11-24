import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Clock,
  Download,
  Key,
  Lock,
  Play,
  RefreshCw,
  Server,
  Shield,
  Square,
  Trash2,
  Unlock,
  Zap,
} from "lucide-react";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  downloadStatsFile,
  fetchStatsSummary,
  fetchTestStatus,
  resetStats,
  startAdminTest,
  stopAdminTest,
  type TestStatusResponse,
  type TestSummaryRow,
} from "../lib/api";

const DEFAULT_ADMIN_TOKEN = "cb-admin-secret-2026";
const WORKER_NAMES = ["worker-1", "worker-2", "worker-3"];

export const OpsCenterPage: React.FC = () => {
  // Authentication state
  const [token, setToken] = useState<string>(() => {
    return sessionStorage.getItem("cb_admin_token") || DEFAULT_ADMIN_TOKEN;
  });
  const [tokenInput, setTokenInput] = useState<string>(token);

  // Test Control Form state
  const [mode, setMode] = useState<string>("milp");
  const [durationSec, setDurationSec] = useState<number>(30);
  const [lambdaPerClient, setLambdaPerClient] = useState<number>(5.0);
  const [heavyRatio, setHeavyRatio] = useState<number>(0.2);
  const [seed, setSeed] = useState<number>(42);

  // Live Test Status state
  const [testStatus, setTestStatus] = useState<TestStatusResponse>({ state: "idle" });
  const [countdown, setCountdown] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Stats Summary state
  const [summaryRows, setSummaryRows] = useState<TestSummaryRow[]>([]);

  // WebSocket Live Snapshot for worker CPU and telemetry
  const { snapshot } = useWebSocket();

  // Test state polling
  const pollStatus = useCallback(async () => {
    try {
      const data = await fetchTestStatus();
      setTestStatus(data);
    } catch {
      // ignore transient poll errors
    }
  }, []);

  const loadSummary = useCallback(async (currToken: string) => {
    if (!currToken) return;
    try {
      const rows = await fetchStatsSummary(currToken);
      setSummaryRows(rows);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    pollStatus();
    const interval = setInterval(pollStatus, 500);
    return () => clearInterval(interval);
  }, [pollStatus]);

  useEffect(() => {
    if (token) {
      loadSummary(token);
    }
  }, [token, loadSummary]);

  // Countdown timer calculation
  useEffect(() => {
    if (testStatus.state === "armed" && testStatus.start_at) {
      const diff = Math.max(0, Math.ceil(testStatus.start_at - Date.now() / 1000));
      setCountdown(diff);
    } else if (
      testStatus.state === "running" &&
      testStatus.start_at &&
      testStatus.duration_s
    ) {
      const endAt = testStatus.start_at + testStatus.duration_s;
      const diff = Math.max(0, Math.ceil(endAt - Date.now() / 1000));
      setCountdown(diff);
    } else {
      setCountdown(null);
    }
  }, [testStatus]);

  // When test transitions to idle, reload stats
  const prevTestState = useRef(testStatus.state);
  useEffect(() => {
    if (prevTestState.current !== "idle" && testStatus.state === "idle" && token) {
      loadSummary(token);
    }
    prevTestState.current = testStatus.state;
  }, [testStatus.state, token, loadSummary]);

  // Auth submission
  const handleSaveToken = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = tokenInput.trim();
    if (!clean) {
      alert("Token cannot be blank");
      return;
    }
    sessionStorage.setItem("cb_admin_token", clean);
    setToken(clean);
    loadSummary(clean);
  };

  // Test Actions
  const handleStartTest = async () => {
    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await startAdminTest(token, {
        mode,
        duration_s: Number(durationSec),
        lambda_per_client: Number(lambdaPerClient),
        heavy_ratio: Number(heavyRatio),
        seed: Number(seed),
      });
      setTestStatus(res);
      setActionMessage(`Test armed successfully! Test ID: ${res.test_id || "armed"}`);
    } catch (err) {
      setActionMessage(`Start Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleStopTest = async () => {
    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await stopAdminTest(token);
      setTestStatus(res);
      setActionMessage("Test stopped. Draining in-flight tasks...");
      setTimeout(() => loadSummary(token), 1000);
    } catch (err) {
      setActionMessage(`Stop Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDownload = async (file: "summary" | "log") => {
    try {
      await downloadStatsFile(token, file);
    } catch (err) {
      alert(`Download failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleResetStats = async () => {
    if (!confirm("Are you sure you want to clear test_summary.csv and test_log.csv?")) {
      return;
    }
    try {
      await resetStats(token);
      setSummaryRows([]);
      setActionMessage("Stats and logs cleared.");
    } catch (err) {
      alert(`Reset failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // Locked mode check
  const isLocked = testStatus.state !== "idle";

  // Comparison metrics: Find latest MILP and Round Robin rows
  const milpRow = summaryRows
    .slice()
    .reverse()
    .find((r) => r.mode?.toLowerCase() === "milp");
  const rrRow = summaryRows
    .slice()
    .reverse()
    .find((r) => r.mode?.toLowerCase() === "round_robin" || r.mode?.toLowerCase() === "rr");

  const calcDiffPct = (milpVal: number, rrVal: number) => {
    if (!rrVal || isNaN(rrVal)) return 0;
    return ((milpVal - rrVal) / rrVal) * 100;
  };

  // Worker telemetry helpers
  const getWorkerTelemetry = (workerId: string) => {
    const w = snapshot?.workers.find((worker) => worker.worker_id === workerId);
    const inFlight = w ? w.active_tasks : 0;
    const cpu = w ? w.cpu_percent : 12.0;
    const isOverloaded = cpu >= 85.0 || inFlight >= 5;
    return {
      cpu,
      inFlight,
      isOverloaded,
    };
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-base tracking-tight text-white">
                  CLOUD<span className="text-cyan-400">BALANCE</span>
                </span>
                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                  /ops Admin
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Cluster Operations & Benchmark Control Center
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              to="/"
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1.5 transition"
            >
              <span>Public Tools (/)</span>
            </Link>
            <Link
              to="/benchmark"
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1.5 transition"
            >
              <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
              <span>Benchmark Lab</span>
            </Link>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6 space-y-6">
        {/* Token Authentication Bar */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 sm:p-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Key className="w-4 h-4 text-cyan-400" />
            <span className="text-xs font-mono text-slate-300">
              Admin Bearer Token:{" "}
              <span className="text-cyan-300 font-bold">
                {token ? `${token.slice(0, 10)}...` : "Not Set"}
              </span>
            </span>
          </div>

          <form onSubmit={handleSaveToken} className="flex items-center gap-2 w-full sm:w-auto">
            <input
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Enter ADMIN_TOKEN"
              className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 w-full sm:w-56"
            />
            <button
              type="submit"
              className="px-3 py-1 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white shrink-0"
            >
              Save Token
            </button>
          </form>
        </div>

        {/* Action Message Alert */}
        {actionMessage && (
          <div className="p-3 rounded-xl bg-slate-900 border border-cyan-500/30 text-cyan-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-cyan-400 shrink-0" />
              <span>{actionMessage}</span>
            </div>
            <button
              onClick={() => setActionMessage(null)}
              className="text-slate-400 hover:text-white text-xs ml-2"
            >
              ✕
            </button>
          </div>
        )}

        {/* Section 1: D3 Controls and Live Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Controls Column (5 cols) */}
          <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
            <div className="border-b border-slate-800 pb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-white flex items-center gap-2">
                  <Shield className="w-4 h-4 text-cyan-400" />
                  Benchmark Test Controls
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Configure and start automated load test runs.
                </p>
              </div>
              {isLocked ? (
                <span className="flex items-center gap-1 text-[11px] font-mono text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">
                  <Lock className="w-3 h-3" /> Locked
                </span>
              ) : (
                <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                  <Unlock className="w-3 h-3" /> Ready
                </span>
              )}
            </div>

            <div className="space-y-3.5">
              {/* Mode Selector - Disabled while running */}
              <div>
                <label className="text-xs font-mono uppercase text-slate-300 block mb-1">
                  Scheduler Mode
                </label>
                <select
                  value={mode}
                  disabled={isLocked}
                  onChange={(e) => setMode(e.target.value)}
                  className={`w-full bg-slate-950 border rounded-xl px-3 py-2 text-xs font-mono text-white focus:outline-none transition ${
                    isLocked
                      ? "border-slate-800 opacity-60 cursor-not-allowed"
                      : "border-slate-700 focus:border-cyan-500"
                  }`}
                >
                  <option value="milp">ortools_milp (MILP Optimization)</option>
                  <option value="round_robin">round_robin (Isolated Strict RR)</option>
                </select>
                {isLocked && (
                  <p className="text-[10px] text-amber-400/80 mt-1">
                    * Mode selector locked while test is active (HTTP 409 protection).
                  </p>
                )}
              </div>

              {/* Grid Inputs: Duration, Lambda */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-mono uppercase text-slate-300 block mb-1">
                    Duration (s)
                  </label>
                  <input
                    type="number"
                    min="5"
                    max="600"
                    disabled={isLocked}
                    value={durationSec}
                    onChange={(e) => setDurationSec(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
                  />
                </div>

                <div>
                  <label className="text-xs font-mono uppercase text-slate-300 block mb-1">
                    λ (req/sec/client)
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    max="50"
                    disabled={isLocked}
                    value={lambdaPerClient}
                    onChange={(e) => setLambdaPerClient(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
                  />
                </div>
              </div>

              {/* Grid Inputs: Heavy Ratio, Seed */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-mono uppercase text-slate-300 block mb-1">
                    Heavy Ratio (0-1)
                  </label>
                  <input
                    type="number"
                    step="0.05"
                    min="0"
                    max="1"
                    disabled={isLocked}
                    value={heavyRatio}
                    onChange={(e) => setHeavyRatio(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
                  />
                </div>

                <div>
                  <label className="text-xs font-mono uppercase text-slate-300 block mb-1">
                    PRNG Seed
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="999999"
                    disabled={isLocked}
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
                  />
                </div>
              </div>

              {/* Start & Stop Action Buttons */}
              <div className="grid grid-cols-2 gap-3 pt-2">
                <button
                  type="button"
                  onClick={handleStartTest}
                  disabled={isLocked || actionLoading}
                  className="py-2.5 rounded-xl font-semibold text-xs bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white flex items-center justify-center gap-1.5 transition shadow-sm"
                >
                  <Play className="w-3.5 h-3.5 fill-white" />
                  <span>Start Test</span>
                </button>

                <button
                  type="button"
                  onClick={handleStopTest}
                  disabled={!isLocked || actionLoading}
                  className="py-2.5 rounded-xl font-semibold text-xs bg-rose-600 hover:bg-rose-500 disabled:bg-slate-800 disabled:text-slate-500 text-white flex items-center justify-center gap-1.5 transition shadow-sm"
                >
                  <Square className="w-3.5 h-3.5 fill-white" />
                  <span>Stop Test</span>
                </button>
              </div>
            </div>
          </div>

          {/* Live Panel Column (7 cols) */}
          <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
            <div className="border-b border-slate-800 pb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-white flex items-center gap-2">
                  <Activity className="w-4 h-4 text-cyan-400" />
                  Live Cluster Telemetry Panel
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Real-time status, countdown timer, and worker load metrics.
                </p>
              </div>

              {/* Live State Badge */}
              <div className="flex items-center gap-2">
                <span
                  className={`text-xs font-mono font-bold uppercase px-3 py-1 rounded-full border flex items-center gap-1.5 ${
                    testStatus.state === "running"
                      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40 animate-pulse"
                      : testStatus.state === "armed"
                        ? "bg-amber-500/15 text-amber-300 border-amber-500/40 animate-pulse"
                        : testStatus.state === "draining"
                          ? "bg-cyan-500/15 text-cyan-300 border-cyan-500/40 animate-pulse"
                          : "bg-slate-800 text-slate-300 border-slate-700"
                  }`}
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      testStatus.state === "running"
                        ? "bg-emerald-400"
                        : testStatus.state === "armed"
                          ? "bg-amber-400"
                          : testStatus.state === "draining"
                            ? "bg-cyan-400"
                            : "bg-slate-400"
                    }`}
                  />
                  {testStatus.state}
                </span>
              </div>
            </div>

            {/* Countdown / Status Info Banner */}
            <div className="bg-slate-950/70 p-4 rounded-xl border border-slate-800 flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="text-[10px] uppercase font-mono text-slate-400 block">
                  Active Test Identifier
                </span>
                <span className="text-xs font-mono text-cyan-300 font-bold">
                  {testStatus.test_id || "None (idle)"}
                </span>
              </div>

              {testStatus.state === "armed" && (
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-amber-400 animate-spin" />
                  <span className="text-xs font-mono text-amber-300">
                    Arming Countdown: <strong className="text-sm font-bold">{countdown}s</strong>
                  </span>
                </div>
              )}

              {testStatus.state === "running" && (
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-emerald-400" />
                  <span className="text-xs font-mono text-emerald-300">
                    Time Remaining: <strong className="text-sm font-bold">{countdown}s</strong>
                  </span>
                </div>
              )}

              {testStatus.state === "draining" && (
                <div className="flex items-center gap-2">
                  <RefreshCw className="w-4 h-4 text-cyan-400 animate-spin" />
                  <span className="text-xs font-mono text-cyan-300">
                    Draining in-flight requests (wait up to 15s)...
                  </span>
                </div>
              )}
            </div>

            {/* Per-Worker In-Flight & CPU Bars with Red Overloaded Badge */}
            <div className="space-y-3 pt-1">
              {WORKER_NAMES.map((wName) => {
                const tel = getWorkerTelemetry(wName);
                return (
                  <div
                    key={wName}
                    className="p-3 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Server className="w-3.5 h-3.5 text-cyan-400" />
                        <span className="text-xs font-mono font-bold text-white">{wName}</span>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                          {tel.inFlight} in-flight
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {tel.isOverloaded && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-extrabold uppercase bg-rose-500/20 text-rose-400 border border-rose-500/50 animate-pulse flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3" /> OVERLOADED
                          </span>
                        )}
                        <span className="text-xs font-mono text-cyan-300 font-bold">
                          {tel.cpu.toFixed(1)}% CPU
                        </span>
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all duration-300 ${
                          tel.cpu >= 85.0
                            ? "bg-rose-500"
                            : tel.cpu >= 65.0
                              ? "bg-amber-400"
                              : "bg-cyan-500"
                        }`}
                        style={{ width: `${Math.min(100, Math.max(2, tel.cpu))}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Section 2: D4 Results & Side-by-Side Comparison */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-6 shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-emerald-400" />
                Benchmark Results & Comparison (D4)
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Side-by-side performance comparison: MILP vs Round Robin with percentage delta.
              </p>
            </div>

            {/* Action Buttons: Downloads & Reset */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => handleDownload("summary")}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-500/30 flex items-center gap-1.5 transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span>test_summary.csv</span>
              </button>

              <button
                type="button"
                onClick={() => handleDownload("log")}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-500/30 flex items-center gap-1.5 transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span>test_log.csv</span>
              </button>

              <button
                type="button"
                onClick={handleResetStats}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-rose-900/40 text-rose-300 border border-rose-500/30 flex items-center gap-1.5 transition"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Reset</span>
              </button>
            </div>
          </div>

          {/* Side-by-Side Comparison Table */}
          {milpRow && rrRow ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 bg-slate-950/60">
                    <th className="py-2.5 px-3">Performance Metric</th>
                    <th className="py-2.5 px-3 text-cyan-400 font-bold">OR-Tools MILP</th>
                    <th className="py-2.5 px-3 text-amber-400 font-bold">Round Robin</th>
                    <th className="py-2.5 px-3">Difference Delta</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {/* avg_ms */}
                  <tr>
                    <td className="py-2.5 px-3 font-medium text-slate-300">Average Latency (avg_ms)</td>
                    <td className="py-2.5 px-3 text-white font-bold">{Number(milpRow.avg_ms).toFixed(2)} ms</td>
                    <td className="py-2.5 px-3 text-white">{Number(rrRow.avg_ms).toFixed(2)} ms</td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(Number(milpRow.avg_ms), Number(rrRow.avg_ms));
                        const isBetter = diff <= 0;
                        return (
                          <span
                            className={`font-bold ${isBetter ? "text-emerald-400" : "text-rose-400"}`}
                          >
                            {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}{" "}
                            {isBetter ? "(MILP Faster)" : "(RR Faster)"}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>

                  {/* p95_ms */}
                  <tr>
                    <td className="py-2.5 px-3 font-medium text-slate-300">P95 Latency (p95_ms)</td>
                    <td className="py-2.5 px-3 text-white font-bold">{Number(milpRow.p95_ms).toFixed(2)} ms</td>
                    <td className="py-2.5 px-3 text-white">{Number(rrRow.p95_ms).toFixed(2)} ms</td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(Number(milpRow.p95_ms), Number(rrRow.p95_ms));
                        const isBetter = diff <= 0;
                        return (
                          <span
                            className={`font-bold ${isBetter ? "text-emerald-400" : "text-rose-400"}`}
                          >
                            {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}{" "}
                            {isBetter ? "(Lower Tail Latency)" : ""}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>

                  {/* failed */}
                  <tr>
                    <td className="py-2.5 px-3 font-medium text-slate-300">Failed / 503 Requests</td>
                    <td className="py-2.5 px-3 text-white font-bold">{milpRow.failed}</td>
                    <td className="py-2.5 px-3 text-white">{rrRow.failed}</td>
                    <td className="py-2.5 px-3">
                      {Number(milpRow.failed) <= Number(rrRow.failed) ? (
                        <span className="text-emerald-400 font-bold">
                          -{Number(rrRow.failed) - Number(milpRow.failed)} fewer failures
                        </span>
                      ) : (
                        <span className="text-rose-400 font-bold">
                          +{Number(milpRow.failed) - Number(rrRow.failed)} failures
                        </span>
                      )}
                    </td>
                  </tr>

                  {/* busy_time_stddev */}
                  <tr>
                    <td className="py-2.5 px-3 font-medium text-slate-300">
                      Busy Time Std-Dev (Load Balance)
                    </td>
                    <td className="py-2.5 px-3 text-white font-bold">
                      {Number(milpRow.busy_time_stddev).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3 text-white">
                      {Number(rrRow.busy_time_stddev).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(
                          Number(milpRow.busy_time_stddev),
                          Number(rrRow.busy_time_stddev)
                        );
                        const isBetter = diff <= 0;
                        return (
                          <span
                            className={`font-bold ${isBetter ? "text-emerald-400" : "text-amber-400"}`}
                          >
                            {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}{" "}
                            {isBetter ? "(More Uniform Balancing)" : ""}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>

                  {/* throughput_rps */}
                  <tr>
                    <td className="py-2.5 px-3 font-medium text-slate-300">Throughput (rps)</td>
                    <td className="py-2.5 px-3 text-white font-bold">
                      {Number(milpRow.throughput_rps).toFixed(2)} req/s
                    </td>
                    <td className="py-2.5 px-3 text-white">
                      {Number(rrRow.throughput_rps).toFixed(2)} req/s
                    </td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(
                          Number(milpRow.throughput_rps),
                          Number(rrRow.throughput_rps)
                        );
                        return (
                          <span className="text-slate-300">
                            {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-5 rounded-xl bg-slate-950/80 border border-slate-800 text-center space-y-1.5">
              <Clock className="w-5 h-5 text-slate-500 mx-auto" />
              <p className="text-xs text-slate-300">
                Awaiting test runs for both <strong>MILP</strong> and <strong>Round Robin</strong>{" "}
                modes to generate side-by-side comparison.
              </p>
              <p className="text-[11px] text-slate-500">
                Run one test in Round Robin mode and one test in MILP mode using the controls above.
              </p>
            </div>
          )}

          {/* Full History Table */}
          <div className="space-y-2">
            <h3 className="text-xs font-mono uppercase text-slate-400 tracking-wider">
              All Completed Test Summaries ({summaryRows.length} runs)
            </h3>

            {summaryRows.length > 0 ? (
              <div className="overflow-x-auto border border-slate-800 rounded-xl">
                <table className="w-full text-left text-xs font-mono border-collapse">
                  <thead>
                    <tr className="bg-slate-950 text-slate-400 border-b border-slate-800">
                      <th className="py-2 px-3">Test ID</th>
                      <th className="py-2 px-3">Mode</th>
                      <th className="py-2 px-3">Duration</th>
                      <th className="py-2 px-3">Reqs</th>
                      <th className="py-2 px-3">Failed</th>
                      <th className="py-2 px-3">Avg Latency</th>
                      <th className="py-2 px-3">P95 Latency</th>
                      <th className="py-2 px-3">Busy StdDev</th>
                      <th className="py-2 px-3">Throughput</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 bg-slate-900/40">
                    {summaryRows.map((r, i) => (
                      <tr key={i} className="hover:bg-slate-800/40 transition">
                        <td className="py-2 px-3 text-cyan-300">{r.test_id}</td>
                        <td className="py-2 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] ${
                              r.mode === "milp"
                                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                                : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                            }`}
                          >
                            {r.mode}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-slate-300">{r.duration_s}s</td>
                        <td className="py-2 px-3 text-white">{r.requests}</td>
                        <td
                          className={`py-2 px-3 ${Number(r.failed) > 0 ? "text-rose-400 font-bold" : "text-emerald-400"}`}
                        >
                          {r.failed}
                        </td>
                        <td className="py-2 px-3 text-white">{Number(r.avg_ms).toFixed(1)} ms</td>
                        <td className="py-2 px-3 text-white">{Number(r.p95_ms).toFixed(1)} ms</td>
                        <td className="py-2 px-3 text-white">{Number(r.busy_time_stddev).toFixed(1)} ms</td>
                        <td className="py-2 px-3 text-slate-300">
                          {Number(r.throughput_rps).toFixed(1)} rps
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">No completed test records in test_summary.csv yet.</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
};

export default OpsCenterPage;
