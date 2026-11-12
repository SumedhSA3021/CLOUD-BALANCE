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
import { Play, Trophy } from "lucide-react";
import { fetchBenchmarkRuns, runNewBenchmark } from "../lib/api";
import type { BenchmarkRun } from "../lib/types";

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export const BenchmarkSection: React.FC = () => {
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [runningNew, setRunningNew] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

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
      const latest = await runNewBenchmark(42, 20);
      setRuns((prev) => [latest, ...prev]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Benchmark trigger failed");
    } finally {
      setRunningNew(false);
    }
  };

  const activeRun = runs[0];
  const schedOrder = ["ortools_milp", "least_connections", "round_robin"];
  const labels = ["OR-Tools MILP", "Least Connections", "Round Robin"];

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300">
            <Trophy className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white">
              3-Scheduler Deterministic Poisson Replay Benchmark
            </h2>
            <p className="text-xs text-slate-400">
              Identical seeded multi-client arrival stream replayed against OR-Tools MILP, Least Connections, and Round Robin
            </p>
          </div>
        </div>

        <button
          type="button"
          disabled={runningNew}
          onClick={() => void handleTriggerRun()}
          className="px-4 py-2 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-slate-950 flex items-center gap-2 transition disabled:opacity-50"
        >
          <Play className="w-3.5 h-3.5" />
          {runningNew ? "Running Seeded Replay..." : "Run Seeded Benchmark (Seed=42)"}
        </button>
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
                      },
                      {
                        label: "Cap Violations (>85% CPU / >90% RAM)",
                        data: schedOrder.map(
                          (k) => activeRun.results[k]?.total_cap_violations ?? 0
                        ),
                        backgroundColor: "rgba(244, 63, 94, 0.75)",
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
                        ticks: { color: "#cbd5e1" },
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
                      },
                      {
                        label: "P95 Completion Latency (ms)",
                        data: schedOrder.map(
                          (k) => activeRun.results[k]?.p95_completion_latency_ms ?? 0
                        ),
                        backgroundColor: "rgba(168, 85, 247, 0.75)",
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
                        ticks: { color: "#cbd5e1" },
                      },
                    },
                  }}
                />
              </div>
            </div>
          </div>

          {/* Summary Comparison Table */}
          <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 overflow-x-auto">
            <h3 className="text-xs font-semibold text-white mb-3">
              Run <code className="text-cyan-300">{activeRun.run_id}</code> — Detailed Metric Comparison ({activeRun.total_tasks} Seeded Tasks)
            </h3>
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                  <th className="py-2 px-3">Scheduler</th>
                  <th className="py-2 px-3">Mean CPU StdDev</th>
                  <th className="py-2 px-3">Peak CPU %</th>
                  <th className="py-2 px-3">Peak RAM %</th>
                  <th className="py-2 px-3">Cap Violations</th>
                  <th className="py-2 px-3">Mean Latency</th>
                  <th className="py-2 px-3">P95 Latency</th>
                  <th className="py-2 px-3">Solver Time</th>
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
                      className={isMilp ? "bg-cyan-500/10 text-white font-semibold" : "text-slate-300"}
                    >
                      <td className="py-2.5 px-3 text-cyan-300">{m.scheduler}</td>
                      <td className="py-2.5 px-3">{m.cpu_stddev_mean.toFixed(2)}%</td>
                      <td className="py-2.5 px-3">{m.peak_cpu_pct.toFixed(1)}%</td>
                      <td className="py-2.5 px-3">{m.peak_mem_pct.toFixed(1)}%</td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-2 py-0.5 rounded ${
                            m.total_cap_violations === 0
                              ? "bg-emerald-500/20 text-emerald-300"
                              : "bg-rose-500/20 text-rose-300"
                          }`}
                        >
                          {m.total_cap_violations}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">{m.mean_completion_latency_ms.toFixed(1)} ms</td>
                      <td className="py-2.5 px-3">{m.p95_completion_latency_ms.toFixed(1)} ms</td>
                      <td className="py-2.5 px-3">{m.mean_solver_latency_ms.toFixed(3)} ms</td>
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

