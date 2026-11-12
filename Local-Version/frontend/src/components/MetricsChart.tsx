import React, { useState } from "react";
import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Title,
  Tooltip,
} from "chart.js";
import { Line } from "react-chartjs-2";
import type { WorkerHistoryPoint, WorkerSnapshotItem } from "../lib/types";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface MetricsChartProps {
  history: WorkerHistoryPoint[];
  workers: WorkerSnapshotItem[];
}

const WORKER_COLORS = [
  { border: "#22d3ee", bg: "rgba(34, 211, 238, 0.12)" },
  { border: "#a855f7", bg: "rgba(168, 85, 247, 0.12)" },
  { border: "#10b981", bg: "rgba(16, 185, 129, 0.12)" },
  { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.12)" },
];

export const MetricsChart: React.FC<MetricsChartProps> = ({ history, workers }) => {
  const [activeTab, setActiveTab] = useState<"cpu" | "ram">("cpu");

  const workerIds = Array.from(
    new Set([
      ...workers.map((w) => w.worker_id),
      ...history.flatMap((h) => Object.keys(h.cpuByWorker)),
    ])
  ).sort();

  const labels = history.map((h) => h.timestampLabel);
  const capLineValue = activeTab === "cpu" ? 85 : 90;

  const datasets = [
    ...workerIds.map((wid, idx) => {
      const palette = WORKER_COLORS[idx % WORKER_COLORS.length];
      return {
        label: wid,
        data: history.map((pt) =>
          activeTab === "cpu"
            ? (pt.cpuByWorker[wid] ?? 0)
            : (pt.memByWorker[wid] ?? 0)
        ),
        borderColor: palette.border,
        backgroundColor: palette.bg,
        borderWidth: 2,
        pointRadius: 1.5,
        tension: 0.3,
        fill: false,
      };
    }),
    {
      label: activeTab === "cpu" ? "MILP CPU Cap (85%)" : "MILP RAM Cap (90%)",
      data: labels.map(() => capLineValue),
      borderColor: "rgba(244, 63, 94, 0.75)",
      borderWidth: 1.5,
      borderDash: [6, 4],
      pointRadius: 0,
      fill: false,
    },
  ];

  return (
    <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-white">
            Real-Time Cluster Telemetry (Rolling 60 Snapshots)
          </h2>
          <p className="text-xs text-slate-400">
            Live feedback loop from worker psutil agents every 2.0s via Redis TTL keys
          </p>
        </div>

        <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-lg border border-slate-800">
          <button
            type="button"
            onClick={() => setActiveTab("cpu")}
            className={`px-3 py-1 rounded text-xs font-medium transition ${
              activeTab === "cpu"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            CPU %
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("ram")}
            className={`px-3 py-1 rounded text-xs font-medium transition ${
              activeTab === "ram"
                ? "bg-purple-500/20 text-purple-300 border border-purple-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            RAM %
          </button>
        </div>
      </div>

      <div className="h-64 w-full">
        <Line
          data={{ labels, datasets }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 200 },
            scales: {
              y: {
                min: 0,
                max: 100,
                grid: { color: "rgba(51, 65, 85, 0.35)" },
                ticks: { color: "#94a3b8", callback: (val) => `${val}%` },
              },
              x: {
                grid: { color: "rgba(51, 65, 85, 0.2)" },
                ticks: { color: "#64748b", maxTicksLimit: 10 },
              },
            },
            plugins: {
              legend: {
                labels: { color: "#cbd5e1", boxWidth: 12, font: { size: 11 } },
              },
            },
          }}
        />
      </div>
    </div>
  );
};

