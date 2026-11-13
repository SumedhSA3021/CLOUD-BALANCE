import React, { useState } from "react";
import { Pause, Play, RefreshCw, Sliders } from "lucide-react";
import type { SchedulerName } from "../lib/types";

interface ControlPanelProps {
  activeScheduler: string;
  lambdaTotal: number;
  paused: boolean;
  onSelectScheduler: (sched: SchedulerName) => Promise<void>;
  onChangeLambda: (rate: number) => Promise<void>;
  onTogglePause: (paused: boolean) => Promise<void>;
  onReviveAllWorkers: () => Promise<void>;
}

const SCHEDULER_OPTIONS: { id: SchedulerName; label: string; desc: string }[] = [
  {
    id: "ortools_milp",
    label: "OR-Tools MILP",
    desc: "Minimax CPU + RAM Caps",
  },
  {
    id: "round_robin",
    label: "Round Robin",
    desc: "Cyclic Pointer (Load-Blind)",
  },
  {
    id: "least_connections",
    label: "Least Connections",
    desc: "Min Active Tasks",
  },
];

export const ControlPanel: React.FC<ControlPanelProps> = ({
  activeScheduler,
  lambdaTotal,
  paused,
  onSelectScheduler,
  onChangeLambda,
  onTogglePause,
  onReviveAllWorkers,
}) => {
  const [sliderValue, setSliderValue] = useState<number>(
    Math.max(1, Math.min(80, Math.round(lambdaTotal || 12)))
  );
  const [busy, setBusy] = useState<boolean>(false);

  const handleSchedulerClick = async (sched: SchedulerName) => {
    setBusy(true);
    try {
      await onSelectScheduler(sched);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-label="Cluster Runtime Control Panel"
      className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-wrap items-center justify-between gap-4"
    >
      {/* Pluggable Scheduler Hot-Swap Toggle */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
          <Sliders className="w-3.5 h-3.5 text-cyan-400" />
          <span>Hot-Swap Active Scheduler (/api/v1/control/scheduler)</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {SCHEDULER_OPTIONS.map((opt) => {
            const isSelected = activeScheduler === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={busy}
                onClick={() => void handleSchedulerClick(opt.id)}
                className={`px-3.5 py-2 rounded-lg text-left border transition ${
                  isSelected
                    ? "bg-cyan-500/20 border-cyan-500 text-white shadow-sm shadow-cyan-500/20"
                    : "bg-slate-950/80 border-slate-800 text-slate-300 hover:border-slate-700"
                }`}
              >
                <div className="text-xs font-bold font-mono">{opt.label}</div>
                <div className="text-[10px] text-slate-400">{opt.desc}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Global Lambda Slider & Action Buttons */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="bg-slate-950/80 border border-slate-800 rounded-lg px-3.5 py-2 space-y-1">
          <div className="flex items-center justify-between gap-4 text-xs">
            <span className="text-slate-400">Target Global &lambda;:</span>
            <span className="font-mono font-bold text-cyan-300">
              {sliderValue} tasks/s
            </span>
          </div>
          <input
            aria-label="Global Lambda Slider"
            type="range"
            min={1}
            max={80}
            value={sliderValue}
            onChange={(e) => {
              const val = Number(e.target.value);
              setSliderValue(val);
              void onChangeLambda(val);
            }}
            className="w-40 accent-cyan-400 cursor-pointer"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void onTogglePause(!paused)}
            className={`px-3.5 py-2.5 rounded-lg text-xs font-semibold border flex items-center gap-1.5 transition ${
              paused
                ? "bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 border-emerald-500/40"
                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
            }`}
          >
            {paused ? (
              <>
                <Play className="w-4 h-4 text-emerald-400" />
                Resume Queue
              </>
            ) : (
              <>
                <Pause className="w-4 h-4 text-slate-300" />
                Pause Queue
              </>
            )}
          </button>

          <button
            type="button"
            disabled={busy}
            onClick={() => void onReviveAllWorkers()}
            className="px-3 py-2.5 rounded-lg text-xs font-medium bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 flex items-center gap-1.5 transition"
            title="Restore any killed workers to active cluster state"
          >
            <RefreshCw className="w-3.5 h-3.5 text-cyan-400" />
            Restore VMs
          </button>
        </div>
      </div>
    </section>
  );
};

