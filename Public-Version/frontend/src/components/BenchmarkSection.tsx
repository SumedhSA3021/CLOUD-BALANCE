import React, { useCallback, useEffect, useState } from "react";
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from "chart.js";
import { Bar } from "react-chartjs-2";
import {
  Activity,
  ArrowDownRight,
  CheckCircle2,
  Clock,
  Play,
  Shield,
  TrendingDown,
  Trophy,
  Zap,
} from "lucide-react";
import { SummaryComparisonPanel } from "./SummaryComparisonPanel";
import { useAdminAuth } from "../context/AdminAuthContext";
import {
  ApiError,
  downloadStatsFile,
  fetchBenchmarkRuns,
  fetchStatsSummary,
  runNewBenchmark,
  type TestSummaryRow,
} from "../lib/api";
import type { BenchmarkRun } from "../lib/types";

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export const BenchmarkSection: React.FC = () => {
  const { token, logout } = useAdminAuth();

  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [runningNew, setRunningNew] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSeed, setSelectedSeed] = useState<number>(42);

  // Completed Test Summaries State
  const [summaryRows, setSummaryRows] = useState<TestSummaryRow[]>([]);
  const [summaryError, setSummaryError] = useState<string | null>(null);

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

  const loadRuns = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const data = await fetchBenchmarkRuns(token);
      setRuns(data);
      setError(null);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(
          err instanceof Error ? err.message : "Failed to load benchmark runs"
        );
      }
    } finally {
      setLoading(false);
    }
  }, [token, handleAuthError]);

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
    void loadRuns();
    void loadSummaries();
  }, [loadRuns, loadSummaries]);

  const handleTriggerRun = async () => {
    if (!token) {
      logout();
      return;
    }
    setRunningNew(true);
    try {
      const latest = await runNewBenchmark(token, selectedSeed, 20);
      setRuns((prev) => [latest, ...prev]);
      setError(null);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Benchmark trigger failed");
      }
    } finally {
      setRunningNew(false);
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
        setSummaryError(
          `Download failed: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    }
  };

  const activeRun = runs[0];
  const schedOrder = ["ortools_milp", "round_robin"];
  const labels = ["OR-Tools MILP", "Round Robin"];

  const milpMetrics = activeRun?.results?.["ortools_milp"];
  const rrMetrics = activeRun?.results?.["round_robin"];

  const imbalanceDelta =
    milpMetrics && rrMetrics && rrMetrics.cpu_stddev_mean > 0
      ? ((milpMetrics.cpu_stddev_mean - rrMetrics.cpu_stddev_mean) /
        rrMetrics.cpu_stddev_mean) *
      100
      : 0;

  const latencyDelta =
    milpMetrics && rrMetrics && rrMetrics.mean_completion_latency_ms > 0
      ? ((milpMetrics.mean_completion_latency_ms -
        rrMetrics.mean_completion_latency_ms) /
        rrMetrics.mean_completion_latency_ms) *
      100
      : 0;

  const p95Delta =
    milpMetrics && rrMetrics && rrMetrics.p95_completion_latency_ms > 0
      ? ((milpMetrics.p95_completion_latency_ms -
        rrMetrics.p95_completion_latency_ms) /
        rrMetrics.p95_completion_latency_ms) *
      100
      : 0;

  const violationsSaved =
    milpMetrics && rrMetrics
      ? rrMetrics.total_cap_violations - milpMetrics.total_cap_violations
      : 0;

  return (
    <div className="space-y-6">
      {/* 1. Replay Simulation Benchmark Header */}
      <div className="rounded-2xl bg-white border border-[#E5DFD3] p-5 shadow-xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-[#E8F3F5] border border-[#B8DCE3] text-[#0F5C6E]">
            <Trophy className="w-5 h-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm sm:text-base font-semibold text-[#1C1917]">
                2-Scheduler Deterministic Poisson Replay Benchmark
              </h2>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-md bg-[#F3EFE6] text-[#0F5C6E] border border-[#E5DFD3]">
                MILP vs Round Robin
              </span>
            </div>
            <p className="text-xs text-[#78716C] mt-0.5">
              Identical seeded multi-client arrival stream replayed against OR-Tools
              MILP and Round Robin.
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center bg-[#F3EFE6] p-1 rounded-xl border border-[#E5DFD3]">
            {[42, 100, 777].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSelectedSeed(s)}
                className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors ${selectedSeed === s
                  ? "bg-white text-[#0F5C6E] font-semibold border border-[#E5DFD3] shadow-xs"
                  : "text-[#57534E] hover:text-[#1C1917]"
                  }`}
              >
                Seed={s}
              </button>
            ))}
          </div>

          <button
            type="button"
            disabled={runningNew}
            onClick={() => void handleTriggerRun()}
            className="min-h-[38px] px-4 py-2 rounded-xl text-xs font-medium bg-[#0F5C6E] hover:bg-[#0B4857] text-white flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5 fill-white" />
            {runningNew
              ? "Replaying Workload..."
              : `Run Seeded Replay (${selectedSeed})`}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="p-3 rounded-xl bg-[#FEE2E2] border border-[#FECACA] text-xs text-[#B91C1C]"
        >
          {error}
        </div>
      )}

      {loading && !activeRun ? (
        <div className="p-10 text-center text-xs text-[#78716C] rounded-2xl bg-white border border-[#E5DFD3]">
          Loading benchmark comparison results...
        </div>
      ) : activeRun ? (
        <>
          {/* KPI Delta Comparison Summary Bar */}
          {milpMetrics && rrMetrics && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
              <div className="p-4 rounded-2xl bg-white border border-[#E5DFD3] shadow-xs flex items-center justify-between">
                <div>
                  <span className="text-[11px] font-medium text-[#78716C] block">
                    Cluster CPU Imbalance
                  </span>
                  <div className="flex items-center gap-1.5 mt-1 tabular-nums">
                    <span
                      className={`text-base font-semibold ${imbalanceDelta <= 0
                        ? "text-[#15803D]"
                        : "text-[#B45309]"
                        }`}
                    >
                      {Math.abs(imbalanceDelta).toFixed(1)}%{" "}
                      {imbalanceDelta <= 0 ? "Lower" : "Higher"}
                    </span>
                    <TrendingDown
                      className={`w-4 h-4 ${imbalanceDelta <= 0
                        ? "text-[#15803D]"
                        : "text-[#B45309] rotate-180"
                        }`}
                    />
                  </div>
                  <span className="text-[11px] text-[#78716C] tabular-nums">
                    MILP {milpMetrics.cpu_stddev_mean.toFixed(1)}% vs RR{" "}
                    {rrMetrics.cpu_stddev_mean.toFixed(1)}%
                  </span>
                </div>
                <div className="p-2.5 rounded-xl bg-[#DCFCE7] border border-[#BBF7D0] text-[#15803D]">
                  <Activity className="w-4 h-4" />
                </div>
              </div>

              <div className="p-4 rounded-2xl bg-white border border-[#E5DFD3] shadow-xs flex items-center justify-between">
                <div>
                  <span className="text-[11px] font-medium text-[#78716C] block">
                    P95 Tail Latency
                  </span>
                  <div className="flex items-center gap-1.5 mt-1 tabular-nums">
                    <span
                      className={`text-base font-semibold ${p95Delta <= 0 ? "text-[#0F5C6E]" : "text-[#B45309]"
                        }`}
                    >
                      {Math.abs(p95Delta).toFixed(1)}%{" "}
                      {p95Delta <= 0 ? "Reduced" : "Higher"}
                    </span>
                    <ArrowDownRight
                      className={`w-4 h-4 ${p95Delta <= 0
                        ? "text-[#0F5C6E]"
                        : "text-[#B45309] -rotate-90"
                        }`}
                    />
                  </div>
                  <span className="text-[11px] text-[#78716C] tabular-nums">
                    MILP {milpMetrics.p95_completion_latency_ms.toFixed(1)}ms vs RR{" "}
                    {rrMetrics.p95_completion_latency_ms.toFixed(1)}ms
                  </span>
                </div>
                <div className="p-2.5 rounded-xl bg-[#E8F3F5] border border-[#B8DCE3] text-[#0F5C6E]">
                  <Zap className="w-4 h-4" />
                </div>
              </div>

              <div className="p-4 rounded-2xl bg-white border border-[#E5DFD3] shadow-xs flex items-center justify-between">
                <div>
                  <span className="text-[11px] font-medium text-[#78716C] block">
                    Mean Latency
                  </span>
                  <div className="flex items-center gap-1.5 mt-1 tabular-nums">
                    <span className="text-base font-semibold text-[#1C1917]">
                      {milpMetrics.mean_completion_latency_ms.toFixed(1)} ms
                    </span>
                    <span
                      className={`text-xs font-mono font-medium ${latencyDelta <= 0
                        ? "text-[#15803D]"
                        : "text-[#B45309]"
                        }`}
                    >
                      ({Math.abs(latencyDelta).toFixed(1)}%{" "}
                      {latencyDelta <= 0 ? "faster" : "slower"})
                    </span>
                  </div>
                  <span className="text-[11px] text-[#78716C] tabular-nums">
                    RR baseline:{" "}
                    {rrMetrics.mean_completion_latency_ms.toFixed(1)}ms
                  </span>
                </div>
                <div className="p-2.5 rounded-xl bg-[#F3EFE6] border border-[#E5DFD3] text-[#4F46E5]">
                  <Clock className="w-4 h-4" />
                </div>
              </div>

              <div className="p-4 rounded-2xl bg-white border border-[#E5DFD3] shadow-xs flex items-center justify-between">
                <div>
                  <span className="text-[11px] font-medium text-[#78716C] block">
                    SLA Violations Avoided
                  </span>
                  <div className="flex items-center gap-1.5 mt-1 tabular-nums">
                    <span
                      className={`text-base font-semibold ${violationsSaved >= 0
                        ? "text-[#15803D]"
                        : "text-[#B45309]"
                        }`}
                    >
                      {violationsSaved > 0
                        ? `-${violationsSaved} Violations`
                        : violationsSaved < 0
                          ? `+${Math.abs(violationsSaved)} Violations`
                          : "0 Violations"}
                    </span>
                    <CheckCircle2
                      className={`w-4 h-4 ${violationsSaved >= 0
                        ? "text-[#15803D]"
                        : "text-[#B45309]"
                        }`}
                    />
                  </div>
                  <span className="text-[11px] text-[#78716C] tabular-nums">
                    MILP ({milpMetrics.total_cap_violations}) vs RR (
                    {rrMetrics.total_cap_violations})
                  </span>
                </div>
                <div className="p-2.5 rounded-xl bg-[#FEE2E2] border border-[#FECACA] text-[#B91C1C]">
                  <Shield className="w-4 h-4" />
                </div>
              </div>
            </div>
          )}

          {/* Side-by-Side Comparison Graphs */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="rounded-2xl bg-white border border-[#E5DFD3] p-5 h-72 flex flex-col shadow-xs">
              <h3 className="text-xs font-semibold text-[#1C1917] mb-3">
                Cluster Load Imbalance (CPU StdDev %) &amp; SLA Cap Violations
                (Lower is Better)
              </h3>
              <div className="flex-1">
                <Bar
                  data={{
                    labels,
                    datasets: [
                      {
                        label: "Mean CPU StdDev (%)",
                        data: schedOrder.map(
                          (k) => activeRun.results[k]?.cpu_stddev_mean ?? 0
                        ),
                        backgroundColor: "rgba(15, 92, 110, 0.85)",
                        borderColor: "#0F5C6E",
                        borderWidth: 1,
                        borderRadius: 6,
                      },
                      {
                        label: "Cap Violations (>85% CPU / >90% RAM)",
                        data: schedOrder.map(
                          (k) => activeRun.results[k]?.total_cap_violations ?? 0
                        ),
                        backgroundColor: "rgba(220, 38, 38, 0.8)",
                        borderColor: "#DC2626",
                        borderWidth: 1,
                        borderRadius: 6,
                      },
                    ],
                  }}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                      legend: {
                        labels: { color: "#44403C", font: { size: 11 } },
                      },
                    },
                    scales: {
                      y: {
                        grid: { color: "rgba(120, 113, 108, 0.16)" },
                        ticks: { color: "#57534E" },
                      },
                      x: {
                        grid: { display: false },
                        ticks: { color: "#1C1917", font: { weight: "bold" } },
                      },
                    },
                  }}
                />
              </div>
            </div>

            <div className="rounded-2xl bg-white border border-[#E5DFD3] p-5 h-72 flex flex-col shadow-xs">
              <h3 className="text-xs font-semibold text-[#1C1917] mb-3">
                Task Completion Latency Mean vs P95 (ms) (Lower is Better)
              </h3>
              <div className="flex-1">
                <Bar
                  data={{
                    labels,
                    datasets: [
                      {
                        label: "Mean Completion Latency (ms)",
                        data: schedOrder.map(
                          (k) =>
                            activeRun.results[k]?.mean_completion_latency_ms ?? 0
                        ),
                        backgroundColor: "rgba(22, 163, 74, 0.82)",
                        borderColor: "#16A34A",
                        borderWidth: 1,
                        borderRadius: 6,
                      },
                      {
                        label: "P95 Completion Latency (ms)",
                        data: schedOrder.map(
                          (k) =>
                            activeRun.results[k]?.p95_completion_latency_ms ?? 0
                        ),
                        backgroundColor: "rgba(79, 70, 229, 0.82)",
                        borderColor: "#4F46E5",
                        borderWidth: 1,
                        borderRadius: 6,
                      },
                    ],
                  }}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                      legend: {
                        labels: { color: "#44403C", font: { size: 11 } },
                      },
                    },
                    scales: {
                      y: {
                        grid: { color: "rgba(120, 113, 108, 0.16)" },
                        ticks: { color: "#57534E" },
                      },
                      x: {
                        grid: { display: false },
                        ticks: { color: "#1C1917", font: { weight: "bold" } },
                      },
                    },
                  }}
                />
              </div>
            </div>
          </div>

          {/* Seeded Replay Metric Comparison Table */}
          <div className="rounded-2xl bg-white border border-[#E5DFD3] p-5 overflow-x-auto shadow-xs">
            <h3 className="text-xs font-semibold text-[#1C1917] mb-3">
              Run{" "}
              <code className="text-[#0F5C6E]">
                {activeRun.run_id ?? "bench-seeded"}
              </code>{" "}
              — Detailed Metric Comparison ({activeRun.total_tasks} Seeded Tasks)
            </h3>
            <table className="w-full text-left border-collapse text-xs font-mono tabular-nums">
              <thead>
                <tr className="border-b border-[#E5DFD3] text-[#57534E] uppercase text-[11px] bg-[#F3EFE6]">
                  <th className="py-2.5 px-3">Scheduler</th>
                  <th className="py-2.5 px-3">Mean CPU StdDev</th>
                  <th className="py-2.5 px-3">Peak CPU %</th>
                  <th className="py-2.5 px-3">Peak RAM %</th>
                  <th className="py-2.5 px-3">Cap Violations</th>
                  <th className="py-2.5 px-3">Mean Latency</th>
                  <th className="py-2.5 px-3">P95 Latency</th>
                  <th className="py-2.5 px-3">Solver Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EFEAE0]">
                {schedOrder.map((key) => {
                  const m = activeRun.results[key];
                  if (!m) return null;
                  const isMilp = key === "ortools_milp";
                  return (
                    <tr
                      key={key}
                      className={
                        isMilp
                          ? "bg-[#E8F3F5]/45 text-[#1C1917] font-semibold"
                          : "text-[#57534E]"
                      }
                    >
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-xs ${isMilp
                            ? "bg-[#E8F3F5] text-[#0F5C6E] border border-[#B8DCE3] font-semibold"
                            : "bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]"
                            }`}
                        >
                          {key}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className={isMilp ? "text-[#0F5C6E]" : ""}>
                          {m.cpu_stddev_mean.toFixed(2)}%
                        </span>
                      </td>
                      <td className="py-3 px-3">{m.peak_cpu_pct.toFixed(1)}%</td>
                      <td className="py-3 px-3">{m.peak_mem_pct.toFixed(1)}%</td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded font-semibold ${m.total_cap_violations === 0
                            ? "bg-[#DCFCE7] text-[#15803D]"
                            : "bg-[#FEE2E2] text-[#B91C1C]"
                            }`}
                        >
                          {m.total_cap_violations}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className={isMilp ? "text-[#15803D]" : ""}>
                          {m.mean_completion_latency_ms.toFixed(1)} ms
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className={isMilp ? "text-[#0F5C6E]" : ""}>
                          {m.p95_completion_latency_ms.toFixed(1)} ms
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        {m.mean_solver_latency_ms.toFixed(3)} ms
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {/* 2. Benchmark Results & Comparison (from test_summary.csv — Admin Only) */}
      <SummaryComparisonPanel
        summaryRows={summaryRows}
        summaryError={summaryError}
        onRefresh={() => void loadSummaries()}
        onDownload={(file) => void handleDownload(file)}
      />
    </div>
  );
};

export default BenchmarkSection;
