import React, { useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  BarChart3,
  Calculator,
  CheckCircle2,
  Cpu,
  Hash,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { submitContractTask, type TaskContractResponse } from "../lib/api";

interface CourseRow {
  id: string;
  name: string;
  credits: number;
  grade: number;
}

export const PublicTasksPage: React.FC = () => {
  // Tab state
  const [activeTab, setActiveTab] = useState<"cgpa" | "hash">("cgpa");

  // CGPA State
  const [courses, setCourses] = useState<CourseRow[]>([
    { id: "1", name: "Cloud Computing & Distributed Systems", credits: 4, grade: 9.0 },
    { id: "2", name: "Algorithm Analysis & Optimization", credits: 4, grade: 8.5 },
    { id: "3", name: "Database Engineering & Storage", credits: 3, grade: 9.0 },
  ]);
  const [cgpaLoading, setCgpaLoading] = useState(false);
  const [cgpaResult, setCgpaResult] = useState<TaskContractResponse | null>(null);
  const [cgpaError, setCgpaError] = useState<string | null>(null);

  // Hash State
  const [hashInput, setHashInput] = useState("cloudbalance-heavy-workload-2026");
  const [hashIterations, setHashIterations] = useState(150000);
  const [hashLoading, setHashLoading] = useState(false);
  const [hashResult, setHashResult] = useState<TaskContractResponse | null>(null);
  const [hashError, setHashError] = useState<string | null>(null);

  // CGPA handlers
  const handleAddCourse = () => {
    setCourses((prev) => [
      ...prev,
      {
        id: String(Date.now()),
        name: `Course ${prev.length + 1}`,
        credits: 3,
        grade: 8.0,
      },
    ]);
  };

  const handleRemoveCourse = (id: string) => {
    if (courses.length <= 1) return;
    setCourses((prev) => prev.filter((c) => c.id !== id));
  };

  const handleUpdateCourse = (id: string, field: "name" | "credits" | "grade", value: any) => {
    setCourses((prev) =>
      prev.map((c) => (c.id === id ? { ...c, [field]: value } : c))
    );
  };

  const handleRunCgpa = async () => {
    setCgpaLoading(true);
    setCgpaError(null);
    try {
      const payload = {
        courses: courses.map((c) => ({
          name: c.name,
          credits: Number(c.credits),
          grade: Number(c.grade),
        })),
      };
      const res = await submitContractTask({
        client_id: "public-web-client",
        task_type: "light",
        payload,
      });
      setCgpaResult(res);
    } catch (err) {
      setCgpaError(err instanceof Error ? err.message : "CGPA computation failed");
    } finally {
      setCgpaLoading(false);
    }
  };

  // Hash handlers
  const handleRunHash = async () => {
    setHashLoading(true);
    setHashError(null);
    try {
      const payload = {
        data: hashInput,
        iterations: Number(hashIterations),
      };
      const res = await submitContractTask({
        client_id: "public-web-client",
        task_type: "heavy",
        size: Number(hashIterations),
        payload,
      });
      setHashResult(res);
    } catch (err) {
      setHashError(err instanceof Error ? err.message : "Heavy hashing computation failed");
    } finally {
      setHashLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Header */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-base tracking-tight text-white">
                  CLOUD<span className="text-cyan-400">BALANCE</span>
                </span>
                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                  Public Tasks
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Distributed Computing Cluster Workload Portal
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              to="/ops"
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1.5 transition"
            >
              <Activity className="w-3.5 h-3.5 text-cyan-400" />
              <span>/ops</span>
            </Link>
            <Link
              to="/benchmark"
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1.5 transition"
            >
              <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
              <span className="hidden sm:inline">Benchmark</span>
            </Link>
          </div>
        </div>
      </header>

      {/* Main Body */}
      <main className="flex-1 max-w-4xl w-full mx-auto px-4 py-6 sm:py-8 space-y-6">
        {/* Intro Banner */}
        <div className="bg-gradient-to-r from-slate-900 via-slate-900 to-cyan-950/40 border border-slate-800 rounded-2xl p-5 sm:p-6 shadow-xl">
          <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight flex items-center gap-2.5">
            <Sparkles className="w-6 h-6 text-cyan-400" />
            Real-Time Cluster Workload Portal
          </h2>
          <p className="text-sm text-slate-300 mt-2 leading-relaxed">
            Submit computational tasks directly to the CloudBalance Controller. Tasks are scheduled
            across real worker nodes with instant latency telemetry and execution metrics.
          </p>

          {/* Workload Tab Selector */}
          <div className="grid grid-cols-2 gap-2 mt-5 bg-slate-950/80 p-1.5 rounded-xl border border-slate-800/80">
            <button
              type="button"
              onClick={() => setActiveTab("cgpa")}
              className={`py-2.5 px-4 rounded-lg text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 transition ${
                activeTab === "cgpa"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Calculator className="w-4 h-4" />
              <span>Lightweight CGPA Tool</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("hash")}
              className={`py-2.5 px-4 rounded-lg text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 transition ${
                activeTab === "hash"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Hash className="w-4 h-4" />
              <span>Heavy SHA-256 Hashing</span>
            </button>
          </div>
        </div>

        {/* Tab 1: CGPA Calculator */}
        {activeTab === "cgpa" && (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-5 shadow-lg">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                  <Calculator className="w-5 h-5 text-cyan-400" />
                  Cumulative Grade Point Average (CGPA) Calculator
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Light task type dispatched to worker nodes with instant score calculation.
                </p>
              </div>
              <button
                type="button"
                onClick={handleAddCourse}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-500/30 flex items-center gap-1.5 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Course
              </button>
            </div>

            {/* Course List */}
            <div className="space-y-3">
              {courses.map((course, idx) => (
                <div
                  key={course.id}
                  className="grid grid-cols-12 gap-2.5 items-center bg-slate-950/60 p-2.5 sm:p-3 rounded-xl border border-slate-800"
                >
                  <div className="col-span-12 sm:col-span-6">
                    <label className="text-[10px] text-slate-400 uppercase font-mono block mb-1">
                      Course Name #{idx + 1}
                    </label>
                    <input
                      type="text"
                      value={course.name}
                      onChange={(e) => handleUpdateCourse(course.id, "name", e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                    />
                  </div>

                  <div className="col-span-5 sm:col-span-2">
                    <label className="text-[10px] text-slate-400 uppercase font-mono block mb-1">
                      Credits
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      min="1"
                      max="10"
                      value={course.credits}
                      onChange={(e) => handleUpdateCourse(course.id, "credits", e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                    />
                  </div>

                  <div className="col-span-5 sm:col-span-3">
                    <label className="text-[10px] text-slate-400 uppercase font-mono block mb-1">
                      Grade (0-10 Scale)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="10"
                      value={course.grade}
                      onChange={(e) => handleUpdateCourse(course.id, "grade", e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                    />
                  </div>

                  <div className="col-span-2 sm:col-span-1 flex items-end justify-center pt-5 sm:pt-0">
                    <button
                      type="button"
                      onClick={() => handleRemoveCourse(course.id)}
                      disabled={courses.length <= 1}
                      className="p-1.5 text-slate-500 hover:text-rose-400 disabled:opacity-30 transition"
                      title="Remove Course"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Submit Button */}
            <button
              type="button"
              onClick={handleRunCgpa}
              disabled={cgpaLoading}
              className="w-full py-3 rounded-xl font-semibold text-sm bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500 text-white flex items-center justify-center gap-2 transition shadow-md shadow-cyan-900/30"
            >
              {cgpaLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Computing on Worker Cluster...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>Dispatch & Calculate CGPA</span>
                </>
              )}
            </button>

            {/* Error Message */}
            {cgpaError && (
              <div className="p-3 rounded-xl bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{cgpaError}</span>
              </div>
            )}

            {/* Mandatory Result Banner: Served by worker-X in N ms */}
            {cgpaResult && (
              <div className="mt-4 p-5 rounded-2xl bg-slate-950 border-2 border-emerald-500/40 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    <span className="text-base font-bold text-white">
                      Served by{" "}
                      <span className="text-cyan-400 underline decoration-cyan-500/50">
                        {cgpaResult.assigned_worker}
                      </span>{" "}
                      in{" "}
                      <span className="text-emerald-400">{cgpaResult.total_ms.toFixed(1)} ms</span>
                    </span>
                  </div>
                  <span
                    className={`px-2.5 py-1 rounded-full text-xs font-mono ${
                      cgpaResult.result?.status === "unavailable"
                        ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                        : "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
                    }`}
                  >
                    {cgpaResult.result?.status === "unavailable" ? "Worker Offline" : "200 OK"}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Calculated CGPA
                    </span>
                    <span className="text-xl font-extrabold text-cyan-300 mt-0.5 block">
                      {cgpaResult.result?.cgpa ?? "N/A"}{" "}
                      <span className="text-xs font-normal text-slate-400">/ 10.0</span>
                    </span>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Total Credits
                    </span>
                    <span className="text-xl font-extrabold text-white mt-0.5 block">
                      {cgpaResult.result?.total_credits ?? "N/A"}
                    </span>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Queue Delay
                    </span>
                    <span className="text-xl font-extrabold text-amber-300 mt-0.5 block">
                      {cgpaResult.queue_ms.toFixed(2)}{" "}
                      <span className="text-xs font-normal text-slate-400">ms</span>
                    </span>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Execution Time
                    </span>
                    <span className="text-xl font-extrabold text-emerald-300 mt-0.5 block">
                      {cgpaResult.exec_ms.toFixed(2)}{" "}
                      <span className="text-xs font-normal text-slate-400">ms</span>
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Heavy Hashing */}
        {activeTab === "hash" && (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-5 shadow-lg">
            <div className="border-b border-slate-800 pb-3">
              <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                <Hash className="w-5 h-5 text-cyan-400" />
                Heavy Workload: SHA-256 Iterative Hashing Loop
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                CPU-intensive hashing loop tuned to generate 0.5 – 1.0 second execution workload on
                e2-micro instances.
              </p>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-xs font-mono text-slate-300 uppercase block mb-1.5">
                  Input Seed Payload String
                </label>
                <input
                  type="text"
                  value={hashInput}
                  onChange={(e) => setHashInput(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500 font-mono"
                  placeholder="Enter text string to digest..."
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-mono text-slate-300 uppercase">
                    Iteration Count (Loop Intensity)
                  </label>
                  <span className="text-xs font-mono text-cyan-400 font-bold">
                    {hashIterations.toLocaleString()} iterations
                  </span>
                </div>

                <div className="flex flex-wrap gap-2 mb-2">
                  {[50000, 150000, 300000, 500000].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setHashIterations(preset)}
                      className={`px-3 py-1 rounded-lg text-xs font-mono border transition ${
                        hashIterations === preset
                          ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/50"
                          : "bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200"
                      }`}
                    >
                      {preset.toLocaleString()}
                    </button>
                  ))}
                </div>

                <input
                  type="range"
                  min="10000"
                  max="1000000"
                  step="10000"
                  value={hashIterations}
                  onChange={(e) => setHashIterations(Number(e.target.value))}
                  className="w-full accent-cyan-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
                />
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="button"
              onClick={handleRunHash}
              disabled={hashLoading}
              className="w-full py-3 rounded-xl font-semibold text-sm bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500 text-white flex items-center justify-center gap-2 transition shadow-md shadow-cyan-900/30"
            >
              {hashLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Computing Iterative Hashing on Worker...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>Dispatch & Run Heavy Hash</span>
                </>
              )}
            </button>

            {/* Error Message */}
            {hashError && (
              <div className="p-3 rounded-xl bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{hashError}</span>
              </div>
            )}

            {/* Mandatory Result Banner: Served by worker-X in N ms */}
            {hashResult && (
              <div className="mt-4 p-5 rounded-2xl bg-slate-950 border-2 border-emerald-500/40 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    <span className="text-base font-bold text-white">
                      Served by{" "}
                      <span className="text-cyan-400 underline decoration-cyan-500/50">
                        {hashResult.assigned_worker}
                      </span>{" "}
                      in{" "}
                      <span className="text-emerald-400">{hashResult.total_ms.toFixed(1)} ms</span>
                    </span>
                  </div>
                  <span
                    className={`px-2.5 py-1 rounded-full text-xs font-mono ${
                      hashResult.result?.status === "unavailable"
                        ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                        : "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
                    }`}
                  >
                    {hashResult.result?.status === "unavailable" ? "Worker Offline" : "200 OK"}
                  </span>
                </div>

                <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-1">
                  <span className="text-[10px] uppercase font-mono text-slate-400 block">
                    Final SHA-256 Digest Hex
                  </span>
                  <p className="text-xs font-mono text-cyan-300 break-all select-all">
                    {hashResult.result?.final_hash ??
                      hashResult.result?.detail ??
                      hashResult.result?.error ??
                      "N/A"}
                  </p>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-1">
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Iterations Run
                    </span>
                    <span className="text-lg font-bold text-white mt-0.5 block">
                      {hashResult.result?.iterations?.toLocaleString() ?? hashIterations.toLocaleString()}
                    </span>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Queue Delay
                    </span>
                    <span className="text-lg font-bold text-amber-300 mt-0.5 block">
                      {hashResult.queue_ms.toFixed(2)}{" "}
                      <span className="text-xs font-normal text-slate-400">ms</span>
                    </span>
                  </div>

                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block">
                      Execution Time
                    </span>
                    <span className="text-lg font-bold text-emerald-300 mt-0.5 block">
                      {hashResult.exec_ms.toFixed(2)}{" "}
                      <span className="text-xs font-normal text-slate-400">ms</span>
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
};

export default PublicTasksPage;
