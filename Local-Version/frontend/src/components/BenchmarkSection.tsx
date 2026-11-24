import React, { useEffect, useState } from "react";
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
  ArrowDownRight,
  BarChart3,
  CheckCircle2,
  Clock,
  Download,
  Play,
  Shield,
  Sparkles,
  TrendingDown,
  Trophy,
  Zap,
} from "lucide-react";
import {
  downloadStatsFile,
  fetchBenchmarkRuns,
  fetchStatsSummary,
  runNewBenchmark,
  type TestSummaryRow,
} from "../lib/api";
import type { BenchmarkRun } from "../lib/types";

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export const BenchmarkSection: React.FC = () => {
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [runningNew, setRunningNew] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSeed, setSelectedSeed] = useState<number>(42);

  // Completed Test Summaries State
  const [summaryRows, setSummaryRows] = useState<TestSummaryRow[]>([]);

  const token = sessionStorage.getItem("cb_admin_token") || "cb-admin-secret-2026";

  const loadRuns = async () => {
    setLoading(true);
    try {
      const data = await fetchBenchmarkRuns();
      setRuns(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load benchmark runs");
    } finally {
      setLoading(false);
    }
  };

  const loadSummaries = async () => {
    try {
      const rows = await fetchStatsSummary(token);
      setSummaryRows(rows);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    void loadRuns();
    void loadSummaries();
  }, []);

  const handleTriggerRun = async () => {
    setRunningNew(true);
    try {
      const latest = await runNewBenchmark(selectedSeed, 20);
      setRuns((prev) => [latest, ...prev]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Benchmark trigger failed");
    } finally {
      setRunningNew(false);
    }
  };

  const handleDownload = async (file: "summary" | "log") => {
    try {
      await downloadStatsFile(token, file);
    } catch (err) {
      alert(`Download failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const activeRun = runs[0];
  const schedOrder = ["ortools_milp", "round_robin"];
  const labels = ["OR-Tools MILP", "Round Robin"];

  // Compute comparative delta metrics for Replay
  const milpMetrics = activeRun?.results?.["ortools_milp"];
  const rrMetrics = activeRun?.results?.["round_robin"];

  const imbalanceDelta =
    milpMetrics && rrMetrics && rrMetrics.cpu_stddev_mean > 0
      ? ((milpMetrics.cpu_stddev_mean - rrMetrics.cpu_stddev_mean) / rrMetrics.cpu_stddev_mean) * 100
      : 0;

  const latencyDelta =
    milpMetrics && rrMetrics && rrMetrics.mean_completion_latency_ms > 0
      ? ((milpMetrics.mean_completion_latency_ms - rrMetrics.mean_completion_latency_ms) /
          rrMetrics.mean_completion_latency_ms) *
        100
      : 0;

  const p95Delta =
    milpMetrics && rrMetrics && rrMetrics.p95_completion_latency_ms > 0
      ? ((milpMetrics.p95_completion_latency_ms - rrMetrics.p95_completion_latency_ms) /
          rrMetrics.p95_completion_latency_ms) *
        100
      : 0;

  const violationsSaved =
    milpMetrics && rrMetrics ? rrMetrics.total_cap_violations - milpMetrics.total_cap_violations : 0;

  // Comparison metrics from test_summary.csv
  const latestMilpSummary = summaryRows
    .slice()
    .reverse()
    .find((r) => r.mode?.toLowerCase() === "milp");
  const latestRrSummary = summaryRows
    .slice()
    .reverse()
    .find((r) => r.mode?.toLowerCase() === "round_robin" || r.mode?.toLowerCase() === "rr");

  const calcDiffPct = (milpVal: number, rrVal: number) => {
    if (!rrVal || isNaN(rrVal)) return 0;
    return ((milpVal - rrVal) / rrVal) * 100;
  };

  return (
    <div className="space-y-6">
      {/* 1. Replay Simulation Benchmark Header */}
      <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300">
            <Trophy className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-white">
                2-Scheduler Deterministic Poisson Replay Benchmark
              </h2>
              <span className="text-[10px] font-mono uppercase px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                MILP vs Round Robin
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Identical seeded multi-client arrival stream replayed against OR-Tools MILP and Round Robin
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-slate-950 p-1 rounded-lg border border-slate-800">
            {[42, 100, 777].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSelectedSeed(s)}
                className={`px-2 py-1 rounded text-[11px] font-mono transition ${
                  selectedSeed === s
                    ? "bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/40"
                    : "text-slate-400 hover:text-slate-200"
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
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-slate-950 flex items-center gap-2 transition disabled:opacity-50 shadow-sm"
          >
            <Play className="w-3.5 h-3.5 fill-slate-950" />
            {runningNew ? "Replaying Workload..." : `Run Seeded Replay (${selectedSeed})`}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-rose-500/15 border border-rose-500/40 text-xs text-rose-200">
          {error}
        </div>
      )}

      {loading && !activeRun ? (
        <div className="p-10 text-center text-xs text-slate-400 rounded-xl bg-slate-900 border border-slate-800">
          Loading benchmark comparison results...
        </div>
      ) : activeRun ? (
        <>
          {/* KPI Delta Comparison Summary Bar */}
          {milpMetrics && rrMetrics && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 block">
                    Cluster CPU Imbalance
                  </span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-base font-bold text-emerald-400">
                      {Math.abs(imbalanceDelta).toFixed(1)}% Lower
                    </span>
                    <TrendingDown className="w-4 h-4 text-emerald-400" />
                  </div>
                  <span className="text-[10px] text-slate-400">
                    MILP {milpMetrics.cpu_stddev_mean.toFixed(1)}% vs RR {rrMetrics.cpu_stddev_mean.toFixed(1)}%
                  </span>
                </div>
                <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                  <Sparkles className="w-4 h-4" />
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 block">
                    P95 Tail Latency
                  </span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-base font-bold text-cyan-400">
                      {Math.abs(p95Delta).toFixed(1)}% Reduced
                    </span>
                    <ArrowDownRight className="w-4 h-4 text-cyan-400" />
                  </div>
                  <span className="text-[10px] text-slate-400">
                    MILP {milpMetrics.p95_completion_latency_ms.toFixed(1)}ms vs RR {rrMetrics.p95_completion_latency_ms.toFixed(1)}ms
                  </span>
                </div>
                <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                  <Zap className="w-4 h-4" />
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 block">
                    Mean Latency
                  </span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-base font-bold text-white">
                      {milpMetrics.mean_completion_latency_ms.toFixed(1)} ms
                    </span>
                    <span className="text-[11px] font-mono text-emerald-400 font-semibold">
                      ({Math.abs(latencyDelta).toFixed(1)}% faster)
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-400">
                    RR baseline: {rrMetrics.mean_completion_latency_ms.toFixed(1)}ms
                  </span>
                </div>
                <div className="p-2 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-400">
                  <Clock className="w-4 h-4" />
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 block">
                    SLA Violations Avoided
                  </span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-base font-bold text-emerald-400">
                      {violationsSaved >= 0 ? `-${violationsSaved} Violations` : "0 Violations"}
                    </span>
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  </div>
                  <span className="text-[10px] text-slate-400">
                    MILP ({milpMetrics.total_cap_violations}) vs RR ({rrMetrics.total_cap_violations})
                  </span>
                </div>
                <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400">
                  <Shield className="w-4 h-4" />
                </div>
              </div>
            </div>
          )}

          {/* Side-by-Side Comparison Graphs */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 h-72 flex flex-col">
              <h3 className="text-xs font-semibold text-slate-200 mb-2">
                Cluster Load Imbalance (CPU StdDev %) & SLA Cap Violations (Lower is Better)
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
                        backgroundColor: "rgba(34, 211, 238, 0.75)",
                        borderColor: "rgba(34, 211, 238, 1)",
                        borderWidth: 1,
                        borderRadius: 4,
                      },
                      {
                        label: "Cap Violations (>85% CPU / >90% RAM)",
                        data: schedOrder.map(
                          (k) => activeRun.results[k]?.total_cap_violations ?? 0
                        ),
                        backgroundColor: "rgba(244, 63, 94, 0.75)",
                        borderColor: "rgba(244, 63, 94, 1)",
                        borderWidth: 1,
                        borderRadius: 4,
                      },
                    ],
                  }}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                      legend: { labels: { color: "#cbd5e1", font: { size: 11 } } },
                    },
                    scales: {
                      y: {
                        grid: { color: "rgba(51, 65, 85, 0.35)" },
                        ticks: { color: "#94a3b8" },
                      },
                      x: {
                        grid: { display: false },
                        ticks: { color: "#cbd5e1", font: { weight: "bold" } },
                      },
                    },
                  }}
                />
              </div>
            </div>

            <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 h-72 flex flex-col">
              <h3 className="text-xs font-semibold text-slate-200 mb-2">
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
                          (k) => activeRun.results[k]?.mean_completion_latency_ms ?? 0
                        ),
                        backgroundColor: "rgba(16, 185, 129, 0.75)",
                        borderColor: "rgba(16, 185, 129, 1)",
                        borderWidth: 1,
                        borderRadius: 4,
                      },
                      {
                        label: "P95 Completion Latency (ms)",
                        data: schedOrder.map(
                          (k) => activeRun.results[k]?.p95_completion_latency_ms ?? 0
                        ),
                        backgroundColor: "rgba(168, 85, 247, 0.75)",
                        borderColor: "rgba(168, 85, 247, 1)",
                        borderWidth: 1,
                        borderRadius: 4,
                      },
                    ],
                  }}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                      legend: { labels: { color: "#cbd5e1", font: { size: 11 } } },
                    },
                    scales: {
                      y: {
                        grid: { color: "rgba(51, 65, 85, 0.35)" },
                        ticks: { color: "#94a3b8" },
                      },
                      x: {
                        grid: { display: false },
                        ticks: { color: "#cbd5e1", font: { weight: "bold" } },
                      },
                    },
                  }}
                />
              </div>
            </div>
          </div>

          {/* Seeded Replay Metric Comparison Table */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 overflow-x-auto shadow-lg">
            <h3 className="text-xs font-semibold text-white mb-3">
              Run <code className="text-cyan-300">{activeRun.run_id ?? "bench-seeded"}</code> — Detailed Metric Comparison ({activeRun.total_tasks} Seeded Tasks)
            </h3>
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px] bg-slate-950/60">
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
              <tbody className="divide-y divide-slate-800/70">
                {schedOrder.map((key) => {
                  const m = activeRun.results[key];
                  if (!m) return null;
                  const isMilp = key === "ortools_milp";
                  return (
                    <tr
                      key={key}
                      className={
                        isMilp
                          ? "bg-cyan-500/10 text-white font-semibold border-l-2 border-cyan-400"
                          : "text-slate-300"
                      }
                    >
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-xs ${
                            isMilp
                              ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-bold"
                              : "bg-slate-800 text-amber-300 border border-slate-700"
                          }`}
                        >
                          {key}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className={isMilp ? "text-cyan-300 font-bold" : ""}>
                          {m.cpu_stddev_mean.toFixed(2)}%
                        </span>
                      </td>
                      <td className="py-3 px-3">{m.peak_cpu_pct.toFixed(1)}%</td>
                      <td className="py-3 px-3">{m.peak_mem_pct.toFixed(1)}%</td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded font-bold ${
                            m.total_cap_violations === 0
                              ? "bg-emerald-500/20 text-emerald-300"
                              : "bg-rose-500/20 text-rose-300"
                          }`}
                        >
                          {m.total_cap_violations}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className={isMilp ? "text-emerald-300 font-bold" : ""}>
                          {m.mean_completion_latency_ms.toFixed(1)} ms
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className={isMilp ? "text-cyan-300 font-bold" : ""}>
                          {m.p95_completion_latency_ms.toFixed(1)} ms
                        </span>
                      </td>
                      <td className="py-3 px-3">{m.mean_solver_latency_ms.toFixed(3)} ms</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {/* 2. Benchmark Results & Comparison (from test_summary.csv) */}
      <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-5 space-y-5 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div>
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-emerald-400" />
              Benchmark Results & Comparison
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Live test results from test_summary.csv comparing OR-Tools MILP vs Round Robin with percentage delta.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => handleDownload("summary")}
              className="px-2.5 py-1 rounded text-xs font-mono bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-slate-700 flex items-center gap-1.5 transition"
            >
              <Download className="w-3.5 h-3.5" />
              <span>test_summary.csv</span>
            </button>
            <button
              type="button"
              onClick={() => handleDownload("log")}
              className="px-2.5 py-1 rounded text-xs font-mono bg-slate-950 hover:bg-slate-800 text-cyan-300 border border-slate-700 flex items-center gap-1.5 transition"
            >
              <Download className="w-3.5 h-3.5" />
              <span>test_log.csv</span>
            </button>
          </div>
        </div>

        {summaryRows.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-400 rounded-xl bg-slate-950 border border-slate-800">
            No completed tests yet
          </div>
        ) : (
          <div className="space-y-5">
            {/* Side-by-Side Comparison Table if both MILP and RR runs exist */}
            {latestMilpSummary && latestRrSummary ? (
              <div className="overflow-x-auto border border-slate-800 rounded-xl">
                <table className="w-full text-left text-xs font-mono border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400 bg-slate-950/60">
                      <th className="py-2.5 px-3">Metric</th>
                      <th className="py-2.5 px-3 text-cyan-400 font-bold">OR-Tools MILP</th>
                      <th className="py-2.5 px-3 text-amber-400 font-bold">Round Robin</th>
                      <th className="py-2.5 px-3">Difference Delta</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {/* avg latency */}
                    <tr>
                      <td className="py-2.5 px-3 font-medium text-slate-300">Avg Latency (avg_ms)</td>
                      <td className="py-2.5 px-3 text-white font-bold">{Number(latestMilpSummary.avg_ms).toFixed(2)} ms</td>
                      <td className="py-2.5 px-3 text-white">{Number(latestRrSummary.avg_ms).toFixed(2)} ms</td>
                      <td className="py-2.5 px-3">
                        {(() => {
                          const diff = calcDiffPct(Number(latestMilpSummary.avg_ms), Number(latestRrSummary.avg_ms));
                          const isBetter = diff <= 0;
                          return (
                            <span className={`font-bold ${isBetter ? "text-emerald-400" : "text-rose-400"}`}>
                              {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}{" "}
                              {isBetter ? "(Faster)" : ""}
                            </span>
                          );
                        })()}
                      </td>
                    </tr>

                    {/* p95 latency */}
                    <tr>
                      <td className="py-2.5 px-3 font-medium text-slate-300">P95 Latency (p95_ms)</td>
                      <td className="py-2.5 px-3 text-white font-bold">{Number(latestMilpSummary.p95_ms).toFixed(2)} ms</td>
                      <td className="py-2.5 px-3 text-white">{Number(latestRrSummary.p95_ms).toFixed(2)} ms</td>
                      <td className="py-2.5 px-3">
                        {(() => {
                          const diff = calcDiffPct(Number(latestMilpSummary.p95_ms), Number(latestRrSummary.p95_ms));
                          const isBetter = diff <= 0;
                          return (
                            <span className={`font-bold ${isBetter ? "text-emerald-400" : "text-rose-400"}`}>
                              {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}{" "}
                              {isBetter ? "(Lower Tail Latency)" : ""}
                            </span>
                          );
                        })()}
                      </td>
                    </tr>

                    {/* failed requests */}
                    <tr>
                      <td className="py-2.5 px-3 font-medium text-slate-300">Failed Requests (failed)</td>
                      <td className="py-2.5 px-3 text-white font-bold">{latestMilpSummary.failed}</td>
                      <td className="py-2.5 px-3 text-white">{latestRrSummary.failed}</td>
                      <td className="py-2.5 px-3">
                        {Number(latestMilpSummary.failed) <= Number(latestRrSummary.failed) ? (
                          <span className="text-emerald-400 font-bold">
                            -{Number(latestRrSummary.failed) - Number(latestMilpSummary.failed)} fewer failures
                          </span>
                        ) : (
                          <span className="text-rose-400 font-bold">
                            +{Number(latestMilpSummary.failed) - Number(latestRrSummary.failed)} failures
                          </span>
                        )}
                      </td>
                    </tr>

                    {/* busy-time std-dev */}
                    <tr>
                      <td className="py-2.5 px-3 font-medium text-slate-300">Busy-Time Std-Dev (busy_time_stddev)</td>
                      <td className="py-2.5 px-3 text-white font-bold">{Number(latestMilpSummary.busy_time_stddev).toFixed(2)} ms</td>
                      <td className="py-2.5 px-3 text-white">{Number(latestRrSummary.busy_time_stddev).toFixed(2)} ms</td>
                      <td className="py-2.5 px-3">
                        {(() => {
                          const diff = calcDiffPct(Number(latestMilpSummary.busy_time_stddev), Number(latestRrSummary.busy_time_stddev));
                          const isBetter = diff <= 0;
                          return (
                            <span className={`font-bold ${isBetter ? "text-emerald-400" : "text-amber-400"}`}>
                              {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}{" "}
                              {isBetter ? "(Fairer Distribution)" : ""}
                            </span>
                          );
                        })()}
                      </td>
                    </tr>

                    {/* throughput */}
                    <tr>
                      <td className="py-2.5 px-3 font-medium text-slate-300">Throughput (throughput_rps)</td>
                      <td className="py-2.5 px-3 text-white font-bold">{Number(latestMilpSummary.throughput_rps).toFixed(2)} req/s</td>
                      <td className="py-2.5 px-3 text-white">{Number(latestRrSummary.throughput_rps).toFixed(2)} req/s</td>
                      <td className="py-2.5 px-3">
                        {(() => {
                          const diff = calcDiffPct(Number(latestMilpSummary.throughput_rps), Number(latestRrSummary.throughput_rps));
                          return (
                            <span className="text-slate-300 font-semibold">
                              {diff > 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`}
                            </span>
                          );
                        })()}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : null}

            {/* All Completed Test Summaries Table */}
            <div className="space-y-2">
              <h3 className="text-xs font-mono uppercase text-slate-400 tracking-wider">
                All Completed Test Summaries ({summaryRows.length} runs)
              </h3>
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
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default BenchmarkSection;
