import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Title,
  Tooltip,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";
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
  Square,
  Trash2,
  Unlock,
  Zap,
} from "lucide-react";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  downloadStatsFile,
  fetchLiveDispatchStats,
  fetchTestStatus,
  resetStats,
  startAdminTest,
  stopAdminTest,
  type LiveDispatchStatsResponse,
  type TestStatusResponse,
} from "../lib/api";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
);

const DEFAULT_ADMIN_TOKEN = "cb-admin-secret-2026";
const WORKER_NAMES = ["worker-1", "worker-2", "worker-3"];

const getBarColor = (pct: number): string => {
  if (pct >= 85.0) return "bg-rose-500";
  if (pct >= 60.0) return "bg-amber-500";
  return "bg-emerald-500";
};

export const OpsCenterPage: React.FC = () => {
  // Row 1: Token Auth State
  const [token, setToken] = useState<string>(() => {
    return sessionStorage.getItem("cb_admin_token") || DEFAULT_ADMIN_TOKEN;
  });
  const [tokenInput, setTokenInput] = useState<string>(token);

  // Row 2: Compact Test Controls State
  const [mode, setMode] = useState<string>("milp");
  const [durationSec, setDurationSec] = useState<number>(30);
  const [lambdaPerClient, setLambdaPerClient] = useState<number>(2.0);
  const [heavyRatio, setHeavyRatio] = useState<number>(0.2);
  const [seed, setSeed] = useState<number>(42);

  // Live Test State
  const [testStatus, setTestStatus] = useState<TestStatusResponse>({ state: "idle" });
  const [countdown, setCountdown] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Row 3: Live Dispatch Stats for graphs
  const [liveStats, setLiveStats] = useState<LiveDispatchStatsResponse | null>(null);

  // WebSocket Live Snapshot for worker CPU, RAM, and in-flight tasks
  const { snapshot } = useWebSocket();

  // Polling loop (every 1.0 second)
  const pollAll = useCallback(async () => {
    try {
      const statusData = await fetchTestStatus();
      setTestStatus(statusData);
    } catch {
      // ignore transient poll errors
    }

    if (token) {
      try {
        const statsData = await fetchLiveDispatchStats(token);
        setLiveStats(statsData);
      } catch {
        // ignore transient poll errors
      }
    }
  }, [token]);

  useEffect(() => {
    pollAll();
    const interval = setInterval(pollAll, 1000);
    return () => clearInterval(interval);
  }, [pollAll]);

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

  // Reset graph when new test starts
  const prevTestId = useRef<string | null>(null);
  useEffect(() => {
    if (testStatus.test_id && testStatus.test_id !== "none" && testStatus.test_id !== prevTestId.current) {
      prevTestId.current = testStatus.test_id;
      if (token) {
        void fetchLiveDispatchStats(token).then((data) => setLiveStats(data));
      }
    }
  }, [testStatus.test_id, token]);

  const handleSaveToken = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = tokenInput.trim();
    if (!clean) {
      alert("Token cannot be blank");
      return;
    }
    sessionStorage.setItem("cb_admin_token", clean);
    setToken(clean);
    setActionMessage("Admin token saved.");
    pollAll();
  };

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
        load_source: "simulator",
      });
      setTestStatus(res);
      setLiveStats(null);
      setActionMessage(`Test armed! Test ID: ${res.test_id || "armed"}`);
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
      setActionMessage("Test logs and summaries cleared.");
    } catch (err) {
      alert(`Reset failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const isLocked = testStatus.state !== "idle";

  // Worker telemetry getter
  const getWorkerTelemetry = (workerId: string) => {
    const w = snapshot?.workers.find((worker) => worker.worker_id === workerId);
    const isOnline = Boolean(w);
    const cpu = w ? w.cpu_percent : 0.0;
    const ram = w ? w.memory_percent : 0.0;
    const inFlight = w ? w.active_tasks : 0;
    const queueLength = w ? (w.queue_length ?? (inFlight > 2 ? inFlight - 2 : 0)) : 0;
    const isOverloaded = isOnline && (cpu >= 85.0 || ram >= 90.0 || queueLength >= 4);

    return {
      isOnline,
      cpu,
      ram,
      inFlight,
      queueLength,
      isOverloaded,
    };
  };

  // Live Chart Data: Last 60s Dispatched Rate
  const chartLabels = liveStats?.labels ?? Array.from({ length: 60 }, (_, i) => (i === 59 ? "now" : `-${59 - i}s`));
  const w1Data = liveStats?.series?.["worker-1"] ?? Array(60).fill(0);
  const w2Data = liveStats?.series?.["worker-2"] ?? Array(60).fill(0);
  const w3Data = liveStats?.series?.["worker-3"] ?? Array(60).fill(0);
  const maxDispatchedPerSec = Math.max(1, ...w1Data, ...w2Data, ...w3Data);

  const lineChartData = {
    labels: chartLabels,
    datasets: [
      {
        label: "worker-1",
        data: w1Data,
        borderColor: "#06b6d4", // cyan
        backgroundColor: "rgba(6, 182, 212, 0.1)",
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: "worker-2",
        data: w2Data,
        borderColor: "#f59e0b", // amber
        backgroundColor: "rgba(245, 158, 11, 0.1)",
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: "worker-3",
        data: w3Data,
        borderColor: "#a855f7", // purple
        backgroundColor: "rgba(168, 85, 247, 0.1)",
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 2,
      },
    ],
  };

  // Cumulative Totals Bar Chart
  const totals = liveStats?.current_test_totals ?? { "worker-1": 0, "worker-2": 0, "worker-3": 0 };
  const totalsBarData = {
    labels: ["worker-1", "worker-2", "worker-3"],
    datasets: [
      {
        label: "Tasks Dispatched",
        data: [totals["worker-1"], totals["worker-2"], totals["worker-3"]],
        backgroundColor: ["#06b6d4", "#f59e0b", "#a855f7"],
        borderRadius: 4,
      },
    ],
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <span className="font-bold text-sm tracking-tight text-white">
                CLOUD<span className="text-cyan-400">BALANCE</span>
              </span>
              <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 ml-2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                /ops
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              to="/"
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
            >
              Public Tools (/)
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

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-5 space-y-4">
        {/* Row 1: Admin Token Bar */}
        <section aria-label="Admin Token Bar" className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs font-mono text-slate-300">
            <Key className="w-3.5 h-3.5 text-cyan-400" />
            <span>Admin Token:</span>
            <span className="text-cyan-400 font-bold">
              {token ? `${token.slice(0, 12)}...` : "Not Set"}
            </span>
          </div>

          <form onSubmit={handleSaveToken} className="flex items-center gap-2 w-full sm:w-auto">
            <input
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Enter ADMIN_TOKEN"
              className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 w-full sm:w-60 font-mono"
            />
            <button
              type="submit"
              className="px-3 py-1 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white shrink-0 transition"
            >
              Save Token
            </button>
          </form>
        </section>

        {/* Action Alert Notification */}
        {actionMessage && (
          <div className="p-2.5 rounded-lg bg-slate-900 border border-cyan-500/30 text-cyan-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
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

        {/* Row 2: Test Controls (Full width and compact) */}
        <section aria-label="Test Controls" className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xs font-mono uppercase tracking-wider text-slate-200 font-bold">
                Test Controls
              </h2>
              {isLocked ? (
                <span className="flex items-center gap-1 text-[11px] font-mono text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">
                  <Lock className="w-3 h-3" /> Locked ({testStatus.state})
                </span>
              ) : (
                <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                  <Unlock className="w-3 h-3" /> Ready
                </span>
              )}

              {/* Live Test Counters */}
              <div className="flex items-center gap-1.5 text-[11px] font-mono ml-2">
                <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300">
                  Sent: <strong className="text-white">{testStatus.sent ?? 0}</strong>
                </span>
                <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/40 text-emerald-400">
                  OK: <strong className="text-emerald-300">{testStatus.ok ?? 0}</strong>
                </span>
                <span
                  className={`px-2 py-0.5 rounded border ${
                    Number(testStatus.failed ?? 0) > 0
                      ? "bg-rose-950/60 border-rose-800/60 text-rose-300 font-bold"
                      : "bg-slate-950 border-slate-800 text-slate-400"
                  }`}
                >
                  Failed: <strong>{testStatus.failed ?? 0}</strong>
                </span>
              </div>
            </div>

            {/* Countdown / State indicator */}
            {testStatus.state === "armed" && (
              <span className="text-xs font-mono text-amber-400 flex items-center gap-1.5 animate-pulse">
                <Clock className="w-3.5 h-3.5" /> Arming in <strong>{countdown}s</strong>
              </span>
            )}
            {testStatus.state === "running" && (
              <span className="text-xs font-mono text-emerald-400 flex items-center gap-1.5 animate-pulse">
                <Clock className="w-3.5 h-3.5" /> Running: <strong>{countdown}s remaining</strong>
              </span>
            )}
            {testStatus.state === "draining" && (
              <span className="text-xs font-mono text-cyan-400 flex items-center gap-1.5 animate-pulse">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Draining in-flight tasks...
              </span>
            )}
          </div>

          {/* Overload Warning Banner if lambda * 3 > 8.0 */}
          {lambdaPerClient * 3 > 8.0 && (
            <div className="p-2 rounded-lg bg-amber-500/15 border border-amber-500/40 text-amber-300 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
              <span>
                <strong>High Rate Warning:</strong> {lambdaPerClient} req/s/client across 3 clients ({(lambdaPerClient * 3).toFixed(1)} req/s total) may saturate local e2-micro / single-machine workers. Default is 2.0 req/s/client.
              </span>
            </div>
          )}

          {/* Compact Input Controls Row */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2.5 items-end">
            {/* Scheduler */}
            <div className="col-span-2 sm:col-span-1 lg:col-span-2">
              <label className="text-[10px] font-mono uppercase text-slate-400 block mb-1">
                Scheduler
              </label>
              <select
                value={mode}
                disabled={isLocked}
                onChange={(e) => setMode(e.target.value)}
                className={`w-full bg-slate-950 border rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none transition ${
                  isLocked ? "border-slate-800 opacity-60 cursor-not-allowed" : "border-slate-700 focus:border-cyan-500"
                }`}
              >
                <option value="milp">ortools_milp</option>
                <option value="round_robin">round_robin</option>
              </select>
            </div>

            {/* Duration (s) */}
            <div>
              <label className="text-[10px] font-mono uppercase text-slate-400 block mb-1">
                Duration (s)
              </label>
              <input
                type="number"
                min="5"
                max="600"
                disabled={isLocked}
                value={durationSec}
                onChange={(e) => setDurationSec(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
              />
            </div>

            {/* Rate λ */}
            <div>
              <label className="text-[10px] font-mono uppercase text-slate-400 block mb-1">
                Rate λ (req/s/client)
              </label>
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="50"
                disabled={isLocked}
                value={lambdaPerClient}
                onChange={(e) => setLambdaPerClient(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
              />
            </div>

            {/* Heavy ratio */}
            <div>
              <label className="text-[10px] font-mono uppercase text-slate-400 block mb-1">
                Heavy ratio
              </label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                disabled={isLocked}
                value={heavyRatio}
                onChange={(e) => setHeavyRatio(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
              />
            </div>

            {/* Seed */}
            <div>
              <label className="text-[10px] font-mono uppercase text-slate-400 block mb-1">
                Seed
              </label>
              <input
                type="number"
                min="1"
                max="999999"
                disabled={isLocked}
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
              />
            </div>

            {/* Start / Stop Action Buttons */}
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={handleStartTest}
                disabled={isLocked || actionLoading}
                className="flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white flex items-center justify-center gap-1 transition"
              >
                <Play className="w-3 h-3 fill-white" />
                <span>Start</span>
              </button>
              <button
                type="button"
                onClick={handleStopTest}
                disabled={!isLocked || actionLoading}
                className="flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold bg-rose-600 hover:bg-rose-500 disabled:bg-slate-800 disabled:text-slate-500 text-white flex items-center justify-center gap-1 transition"
              >
                <Square className="w-3 h-3 fill-white" />
                <span>Stop</span>
              </button>
            </div>
          </div>

          {/* Secondary Row: Downloads & Reset */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80">
            <span className="text-[11px] font-mono text-slate-400">
              Active Test: <strong className="text-cyan-300">{testStatus.test_id || "none"}</strong>
            </span>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleDownload("summary")}
                className="px-2.5 py-1 rounded text-[11px] font-mono bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-slate-700 flex items-center gap-1 transition"
              >
                <Download className="w-3 h-3" />
                <span>test_summary.csv</span>
              </button>
              <button
                type="button"
                onClick={() => handleDownload("log")}
                className="px-2.5 py-1 rounded text-[11px] font-mono bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-slate-700 flex items-center gap-1 transition"
              >
                <Download className="w-3 h-3" />
                <span>test_log.csv</span>
              </button>
              <button
                type="button"
                onClick={handleResetStats}
                className="px-2.5 py-1 rounded text-[11px] font-mono bg-slate-950 hover:bg-rose-950/50 text-rose-300 border border-slate-700 flex items-center gap-1 transition"
              >
                <Trash2 className="w-3 h-3" />
                <span>Reset</span>
              </button>
            </div>
          </div>
        </section>

        {/* Row 3: Live Cluster Panel (Full width, on its own new line) */}
        <section aria-label="Live Cluster Panel" className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2">
            <h2 className="text-xs font-mono uppercase tracking-wider text-slate-200 font-bold flex items-center gap-2">
              <Server className="w-3.5 h-3.5 text-cyan-400" />
              Live Cluster Panel
            </h2>
            <span className="text-[11px] font-mono text-slate-500">
              Telemetry Polled every 1.0s
            </span>
          </div>

          {/* Offline Workers Warning */}
          {(!snapshot?.workers || snapshot.workers.length === 0) && (
            <div className="p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-amber-200 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                <strong>Worker Nodes Offline:</strong> Backend worker processes (ports 8001, 8002, 8003) are not currently running. Tasks dispatched during tests will fail until worker processes are started.
              </span>
            </div>
          )}

          {/* Three Worker Cards Side by Side (Stacked on phone) */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {WORKER_NAMES.map((wName) => {
              const tel = getWorkerTelemetry(wName);
              const cpuColor = getBarColor(tel.cpu);
              const ramColor = getBarColor(tel.ram);

              return (
                <div
                  key={wName}
                  className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-3"
                >
                  {/* Card Header: Worker Name + Badges */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-bold text-white">{wName}</span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      {!tel.isOnline && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-rose-500/20 text-rose-300 border border-rose-500/40 font-semibold">
                          OFFLINE
                        </span>
                      )}
                      {tel.isOverloaded && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-extrabold uppercase bg-rose-500/20 text-rose-400 border border-rose-500/50 animate-pulse flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" /> OVERLOADED
                        </span>
                      )}
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300">
                        {tel.inFlight} in-flight
                      </span>
                    </div>
                  </div>

                  {/* CPU % Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[11px] font-mono">
                      <span className="text-slate-400">CPU</span>
                      <span className="text-white font-semibold">{tel.cpu.toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all duration-300 ${cpuColor}`}
                        style={{ width: `${Math.min(100, Math.max(2, tel.cpu))}%` }}
                      />
                    </div>
                  </div>

                  {/* Memory (RAM) % Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[11px] font-mono">
                      <span className="text-slate-400">Memory (RAM)</span>
                      <span className="text-white font-semibold">{tel.ram.toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all duration-300 ${ramColor}`}
                        style={{ width: `${Math.min(100, Math.max(2, tel.ram))}%` }}
                      />
                    </div>
                  </div>

                  {/* Queue length & Concurrency footer */}
                  <div className="flex items-center justify-between pt-1 border-t border-slate-900 text-[10px] font-mono text-slate-400">
                    <span>Queue Length: <strong className={tel.queueLength > 0 ? "text-amber-400" : "text-slate-300"}>{tel.queueLength}</strong></span>
                    <span>Limit: 2 simultaneous</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Task Distribution Graphs (Under Worker Cards) */}
          <div className="pt-2 border-t border-slate-800/80">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Left: Live Multi-Line Chart (Dispatched tasks / sec over last 60s) */}
              <div className="lg:col-span-2 bg-slate-950 border border-slate-800 rounded-xl p-3 h-64 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-mono font-bold text-slate-200">
                    Task Dispatch Rate (Last 60s)
                  </h3>
                  <span className="text-[10px] font-mono text-slate-500">
                    tasks dispatched / second
                  </span>
                </div>
                <div className="flex-1 relative">
                  <Line
                    data={lineChartData}
                    options={{
                      responsive: true,
                      maintainAspectRatio: false,
                      animation: { duration: 0 },
                      plugins: {
                        legend: {
                          position: "top",
                          labels: { color: "#cbd5e1", font: { size: 10, family: "monospace" }, boxWidth: 12 },
                        },
                      },
                      scales: {
                        y: {
                          beginAtZero: true,
                          suggestedMax: Math.max(2, maxDispatchedPerSec + 1),
                          ticks: { color: "#94a3b8", precision: 0, font: { size: 10 }, stepSize: 1 },
                          grid: { color: "rgba(51, 65, 85, 0.3)" },
                        },
                        x: {
                          ticks: {
                            color: "#94a3b8",
                            font: { size: 9 },
                            maxTicksLimit: 12,
                          },
                          grid: { display: false },
                        },
                      },
                    }}
                  />
                </div>
              </div>

              {/* Right: Cumulative Per-Worker Totals Bar Chart */}
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 h-64 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-mono font-bold text-slate-200">
                    Current Test Totals
                  </h3>
                  <span className="text-[10px] font-mono text-cyan-400 font-bold">
                    {liveStats?.total_dispatched ?? 0} total
                  </span>
                </div>
                <div className="flex-1 relative">
                  <Bar
                    data={totalsBarData}
                    options={{
                      responsive: true,
                      maintainAspectRatio: false,
                      animation: { duration: 200 },
                      plugins: {
                        legend: { display: false },
                      },
                      scales: {
                        y: {
                          beginAtZero: true,
                          suggestedMax: Math.max(2, maxDispatchedPerSec + 1),
                          ticks: { color: "#94a3b8", precision: 0, font: { size: 10 }, stepSize: 1 },
                          grid: { color: "rgba(51, 65, 85, 0.3)" },
                        },
                        x: {
                          ticks: { color: "#cbd5e1", font: { size: 10, family: "monospace" } },
                          grid: { display: false },
                        },
                      },
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

export default OpsCenterPage;
