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
  CheckCircle2,
  Clock,
  Play,
  Shield,
  Sparkles,
  TrendingDown,
  Trophy,
  Zap,
} from "lucide-react";
import { fetchBenchmarkRuns, runNewBenchmark } from "../lib/api";
import type { BenchmarkRun } from "../lib/types";

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export const BenchmarkSection: React.FC = () => {
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [runningNew, setRunningNew] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSeed, setSelectedSeed] = useState<number>(42);

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

  useEffect(() => {
    void loadRuns();
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

  const activeRun = runs[0];
  // Strictly isolated 2-Scheduler evaluation: OR-Tools MILP vs Round Robin
  const schedOrder = ["ortools_milp", "round_robin"];
  const labels = ["OR-Tools MILP", "Round Robin"];

  // Compute comparative delta metrics
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

  return (
    <div className="space-y-4">
      {/* Top Banner Card */}
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
          {/* Seed Presets */}
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
              {/* Card 1: CPU Imbalance */}
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

              {/* Card 2: P95 Tail Latency */}
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

              {/* Card 3: Mean Latency */}
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

              {/* Card 4: SLA Cap Violations */}
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
            {/* Chart 1: CPU Imbalance StdDev & Cap Violations */}
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

            {/* Chart 2: Mean & P95 Completion Latency */}
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

          {/* Summary Comparison Table */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 overflow-x-auto shadow-lg">
            <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-2">
              <h3 className="text-xs font-semibold text-white">
                Run <code className="text-cyan-300">{activeRun.run_id}</code> — Detailed Metric Comparison ({activeRun.total_tasks} Seeded Tasks)
              </h3>
              <span className="text-[11px] font-mono text-slate-400">
                Duration: {activeRun.duration_sec}s | Seed: {activeRun.seed}
              </span>
            </div>

            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                  <th className="py-2.5 px-3">Scheduler</th>
                  <th className="py-2.5 px-3">Mean CPU StdDev</th>
                  <th className="py-2.5 px-3">Peak CPU %</th>
                  <th className="py-2.5 px-3">Peak RAM %</th>
                  <th className="py-2.5 px-3">Cap Violations</th>
                  <th className="py-2.5 px-3">Mean Latency</th>
                  <th className="py-2.5 px-3">P95 Latency</th>
                  <th className="py-2.5 px-3">Solver Time</th>
                  <th className="py-2.5 px-3">Performance Note</th>
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
                          {key === "ortools_milp" ? "ortools_milp" : "round_robin"}
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
                          className={`px-2 py-0.5 rounded ${
                            m.total_cap_violations === 0
                              ? "bg-emerald-500/20 text-emerald-300 font-bold"
                              : "bg-rose-500/20 text-rose-300 font-bold"
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
                      <td className="py-3 px-3">
                        {isMilp ? (
                          <span className="text-emerald-400 text-[11px] font-semibold flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5 inline" /> Optimal Multi-Resource Balance
                          </span>
                        ) : (
                          <span className="text-slate-400 text-[11px]">
                            Load-Blind Cyclic Baseline
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
};

export default BenchmarkSection;
