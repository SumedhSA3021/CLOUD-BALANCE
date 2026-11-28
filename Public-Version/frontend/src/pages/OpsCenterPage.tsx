import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Clock,
  Download,
  Lock,
  Play,
  RefreshCw,
  Server,
  Square,
  Trash2,
  Unlock,
  Zap,
} from "lucide-react";
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
import { Header } from "../components/Header";
import { SummaryComparisonPanel } from "../components/SummaryComparisonPanel";
import { useAdminAuth } from "../context/AdminAuthContext";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  ApiError,
  downloadStatsFile,
  fetchLiveDispatchStats,
  fetchStatsSummary,
  fetchTestStatus,
  resetStats,
  startAdminTest,
  stopAdminTest,
  type LiveDispatchStatsResponse,
  type TestStatusResponse,
  type TestSummaryRow,
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

const WORKER_NAMES = ["worker-1", "worker-2", "worker-3"];

const getBarColor = (pct: number): string => {
  if (pct >= 85.0) return "bg-[#DC2626]";
  if (pct >= 60.0) return "bg-[#D97706]";
  return "bg-[#16A34A]";
};

export const OpsCenterPage: React.FC = () => {
  const { token, logout } = useAdminAuth();

  // Test Controls State
  const [mode, setMode] = useState<string>("milp");
  const [durationSec, setDurationSec] = useState<number>(60);
  const [lambdaPerClient, setLambdaPerClient] = useState<number>(3.0);
  const [heavyRatio, setHeavyRatio] = useState<number>(0.3);
  const [seed, setSeed] = useState<number>(42);

  // Live Test State
  const [testStatus, setTestStatus] = useState<TestStatusResponse>({
    state: "idle",
  });
  const [countdown, setCountdown] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Live Dispatch Stats & Summary Results State
  const [liveStats, setLiveStats] = useState<LiveDispatchStatsResponse | null>(
    null
  );
  const [summaryRows, setSummaryRows] = useState<TestSummaryRow[]>([]);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  // WebSocket Live Snapshot for header + worker telemetry
  const { snapshot, connectionState, isStale } = useWebSocket(token, logout);

  const handleAuthError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return true;
      }
      return false;
    },
    [logout]
  );

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
      } catch (err) {
        handleAuthError(err);
      }
    }
  }, [token, handleAuthError]);

  useEffect(() => {
    void pollAll();
    const interval = setInterval(() => void pollAll(), 1000);
    return () => clearInterval(interval);
  }, [pollAll]);

  // Countdown timer calculation
  useEffect(() => {
    if (testStatus.state === "armed" && testStatus.start_at) {
      const diff = Math.max(
        0,
        Math.ceil(testStatus.start_at - Date.now() / 1000)
      );
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

  const loadSummaries = useCallback(async () => {
    if (!token) return;
    try {
      const rows = await fetchStatsSummary(token);
      setSummaryRows(rows);
      setSummaryError(null);
    } catch (err) {
      if (!handleAuthError(err)) {
        setSummaryError(
          err instanceof Error ? err.message : "Failed to load test summaries"
        );
      }
    }
  }, [token, handleAuthError]);

  useEffect(() => {
    void loadSummaries();
  }, [loadSummaries]);

  // Reset graph when a new test starts; refresh summaries when returning to idle
  const prevTestId = useRef<string | null>(null);
  const prevStateRef = useRef<string>("idle");
  useEffect(() => {
    if (
      testStatus.test_id &&
      testStatus.test_id !== "none" &&
      testStatus.test_id !== prevTestId.current
    ) {
      prevTestId.current = testStatus.test_id;
      if (token) {
        void fetchLiveDispatchStats(token)
          .then((data) => setLiveStats(data))
          .catch((err) => handleAuthError(err));
      }
    }
    if (prevStateRef.current !== "idle" && testStatus.state === "idle") {
      void loadSummaries();
    }
    prevStateRef.current = testStatus.state;
  }, [testStatus.test_id, testStatus.state, token, handleAuthError, loadSummaries]);

  const handleStartTest = async () => {
    if (!token) {
      logout();
      return;
    }

    const dur = Number(durationSec);
    const lam = Number(lambdaPerClient);
    const hr = Number(heavyRatio);
    const sd = Number(seed);

    if (!Number.isFinite(dur) || dur <= 0 || dur > 120) {
      setActionMessage(
        "Start Error: Duration must be between 1 and 120 seconds."
      );
      return;
    }
    if (!Number.isFinite(lam) || lam <= 0 || lam > 100) {
      setActionMessage(
        "Start Error: Rate λ must be between 0.1 and 100 req/s/client."
      );
      return;
    }
    if (!Number.isFinite(hr) || hr < 0 || hr > 1) {
      setActionMessage(
        "Start Error: Heavy ratio must be between 0.0 and 1.0."
      );
      return;
    }
    if (!Number.isFinite(sd)) {
      setActionMessage("Start Error: Seed must be a valid integer.");
      return;
    }

    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await startAdminTest(token, {
        mode,
        duration_s: dur,
        lambda_per_client: lam,
        heavy_ratio: hr,
        seed: Math.trunc(sd),
        load_source: "external",
      });
      setTestStatus(res);
      setLiveStats(null);
      setActionMessage(`Test armed! Test ID: ${res.test_id || "armed"}`);
    } catch (err) {
      if (!handleAuthError(err)) {
        setActionMessage(
          `Start Error: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleStopTest = async () => {
    if (!token) {
      logout();
      return;
    }
    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await stopAdminTest(token);
      setTestStatus(res);
      setActionMessage("Test stopped. Draining in-flight tasks...");
    } catch (err) {
      if (!handleAuthError(err)) {
        setActionMessage(
          `Stop Error: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleDownload = async (file: "summary" | "log") => {
    if (!token) {
      logout();
      return;
    }
    try {
      await downloadStatsFile(token, file);
    } catch (err) {
      if (!handleAuthError(err)) {
        setActionMessage(
          `Download failed: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    }
  };

  const handleResetStats = async () => {
    if (!token) {
      logout();
      return;
    }
    if (
      !confirm("Are you sure you want to clear test_summary.csv and test_log.csv?")
    ) {
      return;
    }
    try {
      await resetStats(token);
      setLiveStats(null);
      setTestStatus((prev) => ({ ...prev, sent: 0, ok: 0, failed: 0 }));
      setActionMessage("Test logs and summaries cleared.");
      void pollAll();
    } catch (err) {
      if (!handleAuthError(err)) {
        setActionMessage(
          `Reset failed: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    }
  };

  const isLocked = testStatus.state !== "idle";

  const getWorkerTelemetry = (workerId: string) => {
    const w = snapshot?.workers.find((worker) => worker.worker_id === workerId);
    const isOnline = Boolean(w);
    const cpu = w ? w.cpu_percent : 0.0;
    const ram = w ? w.memory_percent : 0.0;
    const inFlight = w ? w.active_tasks : 0;
    const queueLength = w
      ? (w.queue_length ?? (inFlight > 2 ? inFlight - 2 : 0))
      : 0;
    const isOverloaded =
      isOnline && (cpu >= 85.0 || ram >= 90.0 || queueLength >= 4);

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
  const chartLabels =
    liveStats?.labels ??
    Array.from({ length: 60 }, (_, i) => (i === 59 ? "now" : `-${59 - i}s`));
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
        borderColor: "#0F5C6E",
        backgroundColor: "rgba(15, 92, 110, 0.08)",
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: "worker-2",
        data: w2Data,
        borderColor: "#C26D1F",
        backgroundColor: "rgba(194, 109, 31, 0.08)",
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: "worker-3",
        data: w3Data,
        borderColor: "#4F46E5",
        backgroundColor: "rgba(79, 70, 229, 0.08)",
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      },
    ],
  };

  const totals = liveStats?.current_test_totals ?? {
    "worker-1": 0,
    "worker-2": 0,
    "worker-3": 0,
  };
  const maxTotalDispatched = Math.max(
    1,
    totals["worker-1"] ?? 0,
    totals["worker-2"] ?? 0,
    totals["worker-3"] ?? 0
  );
  const totalsBarData = {
    labels: ["worker-1", "worker-2", "worker-3"],
    datasets: [
      {
        label: "Tasks Dispatched",
        data: [totals["worker-1"], totals["worker-2"], totals["worker-3"]],
        backgroundColor: ["#0F5C6E", "#C26D1F", "#4F46E5"],
        borderRadius: 6,
      },
    ],
  };

  return (
    <div className="min-h-screen bg-[#FAF7F2] text-[#1C1917] flex flex-col font-sans">
      <Header
        mode="admin"
        snapshot={snapshot}
        connectionState={connectionState}
        isStale={isStale}
        onSignOut={logout}
      />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 py-6 space-y-5">
        {actionMessage && (
          <div className="p-3 rounded-xl bg-[#E8F3F5] border border-[#B8DCE3] text-[#0B4857] text-xs font-medium flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap className="w-3.5 h-3.5 text-[#0F5C6E] shrink-0" />
              <span>{actionMessage}</span>
            </div>
            <button
              type="button"
              onClick={() => setActionMessage(null)}
              className="text-[#57534E] hover:text-[#1C1917] text-xs ml-2 px-1"
            >
              ✕
            </button>
          </div>
        )}

        {/* Test Controls (Admin Only — includes CSV downloads & Reset) */}
        <section
          aria-label="Test Controls"
          className="bg-white border border-[#E5DFD3] rounded-2xl p-5 shadow-xs space-y-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#EFEAE0] pb-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[#1C1917]">
                Test Controls
              </h2>
              {isLocked ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-mono font-medium text-[#B45309] bg-[#FEF3C7] px-2.5 py-0.5 rounded-full border border-[#FDE68A]">
                  <Lock className="w-3 h-3" /> Locked ({testStatus.state})
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-[11px] font-mono font-medium text-[#15803D] bg-[#DCFCE7] px-2.5 py-0.5 rounded-full border border-[#BBF7D0]">
                  <Unlock className="w-3 h-3" /> Ready
                </span>
              )}

              {/* Live Test Counters */}
              <div className="flex items-center gap-1.5 text-[11px] font-mono tabular-nums ml-1">
                <span className="px-2.5 py-0.5 rounded-md bg-[#FAF7F2] border border-[#E5DFD3] text-[#57534E]">
                  Sent:{" "}
                  <strong className="text-[#1C1917]">
                    {testStatus.sent ?? 0}
                  </strong>
                </span>
                <span className="px-2.5 py-0.5 rounded-md bg-[#DCFCE7]/60 border border-[#BBF7D0] text-[#15803D]">
                  OK: <strong>{testStatus.ok ?? 0}</strong>
                </span>
                <span
                  className={`px-2.5 py-0.5 rounded-md border ${
                    Number(testStatus.failed ?? 0) > 0
                      ? "bg-[#FEE2E2] border-[#FECACA] text-[#B91C1C] font-semibold"
                      : "bg-[#FAF7F2] border-[#E5DFD3] text-[#78716C]"
                  }`}
                >
                  Failed: <strong>{testStatus.failed ?? 0}</strong>
                </span>
              </div>
            </div>

            {testStatus.state === "armed" && (
              <span className="text-xs font-mono text-[#B45309] flex items-center gap-1.5 tabular-nums">
                <Clock className="w-3.5 h-3.5" /> Arming in{" "}
                <strong>{countdown}s</strong>
              </span>
            )}
            {testStatus.state === "running" && (
              <span className="text-xs font-mono text-[#15803D] flex items-center gap-1.5 tabular-nums">
                <Clock className="w-3.5 h-3.5" /> Running:{" "}
                <strong>{countdown}s remaining</strong>
              </span>
            )}
            {testStatus.state === "draining" && (
              <span className="text-xs font-mono text-[#0F5C6E] flex items-center gap-1.5">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Draining
                in-flight tasks...
              </span>
            )}
          </div>

          {lambdaPerClient * 3 > 8.0 && (
            <div className="p-2.5 rounded-xl bg-[#FEF3C7] border border-[#FDE68A] text-[#92400E] text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-[#B45309]" />
              <span>
                <strong>High Rate Warning:</strong> {lambdaPerClient} req/s/client
                across 3 clients ({(lambdaPerClient * 3).toFixed(1)} req/s total)
                may saturate single-machine workers. Default is 3.0 req/s/client.
              </span>
            </div>
          )}

          {/* Compact Parameter Inputs & Start/Stop */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3 items-end">
            <div className="col-span-2 sm:col-span-1 lg:col-span-2">
              <label className="text-[11px] font-medium text-[#57534E] block mb-1">
                Scheduler
              </label>
              <select
                value={mode}
                disabled={isLocked}
                onChange={(e) => setMode(e.target.value)}
                className={`w-full min-h-[38px] bg-[#FAF7F2] border rounded-lg px-2.5 py-1.5 text-xs font-mono text-[#1C1917] focus:outline-none transition-colors ${
                  isLocked
                    ? "border-[#E5DFD3] opacity-60 cursor-not-allowed"
                    : "border-[#D6CFC2] focus:border-[#0F5C6E]"
                }`}
              >
                <option value="milp">ortools_milp</option>
                <option value="round_robin">round_robin</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] font-medium text-[#57534E] block mb-1">
                Duration (s)
              </label>
              <input
                type="number"
                min="5"
                max="120"
                disabled={isLocked}
                value={durationSec}
                onChange={(e) => setDurationSec(Number(e.target.value))}
                className="w-full min-h-[38px] bg-[#FAF7F2] border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs font-mono tabular-nums text-[#1C1917] focus:outline-none focus:border-[#0F5C6E] disabled:opacity-60"
              />
            </div>

            <div>
              <label className="text-[11px] font-medium text-[#57534E] block mb-1">
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
                className="w-full min-h-[38px] bg-[#FAF7F2] border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs font-mono tabular-nums text-[#1C1917] focus:outline-none focus:border-[#0F5C6E] disabled:opacity-60"
              />
            </div>

            <div>
              <label className="text-[11px] font-medium text-[#57534E] block mb-1">
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
                className="w-full min-h-[38px] bg-[#FAF7F2] border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs font-mono tabular-nums text-[#1C1917] focus:outline-none focus:border-[#0F5C6E] disabled:opacity-60"
              />
            </div>

            <div>
              <label className="text-[11px] font-medium text-[#57534E] block mb-1">
                Seed
              </label>
              <input
                type="number"
                min="1"
                max="999999"
                disabled={isLocked}
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                className="w-full min-h-[38px] bg-[#FAF7F2] border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs font-mono tabular-nums text-[#1C1917] focus:outline-none focus:border-[#0F5C6E] disabled:opacity-60"
              />
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleStartTest}
                disabled={isLocked || actionLoading}
                className="flex-1 min-h-[38px] py-1.5 px-3 rounded-lg text-xs font-medium bg-[#0F5C6E] hover:bg-[#0B4857] disabled:bg-[#E5DFD3] disabled:text-[#78716C] text-white flex items-center justify-center gap-1.5 transition-colors"
              >
                <Play className="w-3 h-3 fill-white" />
                <span>Start</span>
              </button>
              <button
                type="button"
                onClick={handleStopTest}
                disabled={!isLocked || actionLoading}
                className="flex-1 min-h-[38px] py-1.5 px-3 rounded-lg text-xs font-medium bg-[#B91C1C] hover:bg-[#991B1B] disabled:bg-[#E5DFD3] disabled:text-[#78716C] text-white flex items-center justify-center gap-1.5 transition-colors"
              >
                <Square className="w-3 h-3 fill-white" />
                <span>Stop</span>
              </button>
            </div>
          </div>

          {/* Admin-only CSV Exports & Log Reset */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-[#EFEAE0]">
            <span className="text-xs font-mono text-[#57534E]">
              Active Test:{" "}
              <strong className="text-[#0F5C6E]">
                {testStatus.test_id || "none"}
              </strong>
            </span>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => handleDownload("summary")}
                className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono bg-[#FAF7F2] hover:bg-[#E8F3F5] text-[#0F5C6E] border border-[#D6CFC2] hover:border-[#B8DCE3] flex items-center gap-1.5 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span>test_summary.csv</span>
              </button>
              <button
                type="button"
                onClick={() => handleDownload("log")}
                className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono bg-[#FAF7F2] hover:bg-[#E8F3F5] text-[#0F5C6E] border border-[#D6CFC2] hover:border-[#B8DCE3] flex items-center gap-1.5 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span>test_log.csv</span>
              </button>
              <button
                type="button"
                disabled={isLocked}
                onClick={handleResetStats}
                className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono bg-[#FAF7F2] hover:bg-[#FEE2E2] text-[#B91C1C] border border-[#D6CFC2] hover:border-[#FECACA] flex items-center gap-1.5 transition-colors disabled:opacity-40"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Reset</span>
              </button>
            </div>
          </div>
        </section>

        {/* Live Cluster Panel */}
        <section
          aria-label="Live Cluster Panel"
          className="bg-white border border-[#E5DFD3] rounded-2xl p-5 shadow-xs space-y-5"
        >
          <div className="flex items-center justify-between border-b border-[#EFEAE0] pb-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#1C1917] flex items-center gap-2">
              <Server className="w-4 h-4 text-[#0F5C6E]" />
              Live Cluster Panel
            </h2>
            <span className="text-xs font-mono text-[#78716C]">
              Polled every 1.0s
            </span>
          </div>

          {(!snapshot?.workers || snapshot.workers.length === 0) && (
            <div className="p-3 rounded-xl bg-[#FEF3C7] border border-[#FDE68A] text-[#92400E] text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-[#B45309] shrink-0" />
              <span>
                <strong>Worker Nodes Offline:</strong> Backend worker processes
                are not currently running. Tasks dispatched during tests will
                fail until workers are started.
              </span>
            </div>
          )}

          {/* Three Worker Cards Side by Side */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {WORKER_NAMES.map((wName) => {
              const tel = getWorkerTelemetry(wName);
              const cpuColor = getBarColor(tel.cpu);
              const ramColor = getBarColor(tel.ram);

              return (
                <div
                  key={wName}
                  className="bg-[#FAF7F2] border border-[#E5DFD3] rounded-xl p-4 space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono font-semibold text-[#1C1917]">
                      {wName}
                    </span>

                    <div className="flex items-center gap-1.5">
                      {!tel.isOnline && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-[#FEE2E2] text-[#B91C1C] border border-[#FECACA] font-semibold">
                          OFFLINE
                        </span>
                      )}
                      {tel.isOverloaded && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase bg-[#FEE2E2] text-[#B91C1C] border border-[#FECACA] flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" /> OVERLOADED
                        </span>
                      )}
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-white border border-[#E5DFD3] text-[#44403C] tabular-nums">
                        {tel.inFlight} in-flight
                      </span>
                    </div>
                  </div>

                  {/* CPU % Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs font-mono tabular-nums">
                      <span className="text-[#57534E]">CPU</span>
                      <span className="text-[#1C1917] font-semibold">
                        {tel.cpu.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-[#E5DFD3] rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-[width] duration-300 ${cpuColor}`}
                        style={{
                          width: `${Math.min(100, Math.max(2, tel.cpu))}%`,
                        }}
                      />
                    </div>
                  </div>

                  {/* Memory (RAM) % Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs font-mono tabular-nums">
                      <span className="text-[#57534E]">Memory (RAM)</span>
                      <span className="text-[#1C1917] font-semibold">
                        {tel.ram.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-[#E5DFD3] rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-[width] duration-300 ${ramColor}`}
                        style={{
                          width: `${Math.min(100, Math.max(2, tel.ram))}%`,
                        }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-2 border-t border-[#E5DFD3] text-[11px] font-mono text-[#57534E] tabular-nums">
                    <span>
                      Queue Length:{" "}
                      <strong
                        className={
                          tel.queueLength > 0
                            ? "text-[#B45309]"
                            : "text-[#1C1917]"
                        }
                      >
                        {tel.queueLength}
                      </strong>
                    </span>
                    <span>Limit: 2 simultaneous</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Task Distribution Graphs */}
          <div className="pt-2 border-t border-[#EFEAE0]">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 bg-[#FAF7F2] border border-[#E5DFD3] rounded-xl p-4 h-64 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold text-[#1C1917]">
                    Task Dispatch Rate (Last 60s)
                  </h3>
                  <span className="text-[11px] font-mono text-[#78716C]">
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
                          labels: {
                            color: "#44403C",
                            font: { size: 11, family: "monospace" },
                            boxWidth: 12,
                          },
                        },
                      },
                      scales: {
                        y: {
                          beginAtZero: true,
                          suggestedMax: Math.max(2, maxDispatchedPerSec + 1),
                          ticks: {
                            color: "#57534E",
                            precision: 0,
                            font: { size: 10 },
                            stepSize: 1,
                          },
                          grid: { color: "rgba(120, 113, 108, 0.16)" },
                        },
                        x: {
                          ticks: {
                            color: "#78716C",
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

              <div className="bg-[#FAF7F2] border border-[#E5DFD3] rounded-xl p-4 h-64 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold text-[#1C1917]">
                    Current Test Totals
                  </h3>
                  <span className="text-xs font-mono text-[#0F5C6E] font-semibold tabular-nums">
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
                          suggestedMax: Math.max(2, maxTotalDispatched + 1),
                          ticks: {
                            color: "#57534E",
                            precision: 0,
                            font: { size: 10 },
                          },
                          grid: { color: "rgba(120, 113, 108, 0.16)" },
                        },
                        x: {
                          ticks: {
                            color: "#44403C",
                            font: { size: 10, family: "monospace" },
                          },
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

        <SummaryComparisonPanel
          summaryRows={summaryRows}
          summaryError={summaryError}
          onRefresh={() => void loadSummaries()}
          onDownload={(file) => void handleDownload(file)}
          showDownloads={false}
        />
      </main>
    </div>
  );
};

export default OpsCenterPage;
