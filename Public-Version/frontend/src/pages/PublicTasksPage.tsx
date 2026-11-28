import React, { useState } from "react";
import {
  AlertCircle,
  Calculator,
  CheckCircle2,
  Cpu,
  Hash,
  Play,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { ApiError, submitContractTask, type TaskContractResponse } from "../lib/api";
import {
  buildHeavyHashRequest,
  buildLightCgpaRequest,
  DEFAULT_CGPA_COURSES,
  DEFAULT_HASH_INPUT,
  DEFAULT_HASH_ITERATIONS,
} from "../lib/taskPayloads";

interface CourseRow {
  id: string;
  name: string;
  credits: number;
  grade: number;
}

export const PublicTasksPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"cgpa" | "hash">("cgpa");

  // CGPA State
  const [courses, setCourses] = useState<CourseRow[]>(() =>
    DEFAULT_CGPA_COURSES.map((c, idx) => ({
      id: c.id ?? String(idx + 1),
      name: c.name,
      credits: c.credits,
      grade: c.grade,
    }))
  );
  const [cgpaLoading, setCgpaLoading] = useState(false);
  const [cgpaResult, setCgpaResult] = useState<TaskContractResponse | null>(null);
  const [cgpaError, setCgpaError] = useState<string | null>(null);

  // Hash State
  const [hashInput, setHashInput] = useState(DEFAULT_HASH_INPUT);
  const [hashIterations, setHashIterations] = useState(DEFAULT_HASH_ITERATIONS);
  const [hashLoading, setHashLoading] = useState(false);
  const [hashResult, setHashResult] = useState<TaskContractResponse | null>(null);
  const [hashError, setHashError] = useState<string | null>(null);

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

  const handleUpdateCourse = (
    id: string,
    field: "name" | "credits" | "grade",
    value: string | number
  ) => {
    setCourses((prev) =>
      prev.map((c) => (c.id === id ? { ...c, [field]: value } : c))
    );
  };

  const handleRunCgpa = async () => {
    setCgpaError(null);
    for (const c of courses) {
      const cr = Number(c.credits);
      const gr = Number(c.grade);
      if (!Number.isFinite(cr) || cr <= 0) {
        setCgpaError("Each course must have positive credits (> 0).");
        return;
      }
      if (!Number.isFinite(gr) || gr < 0 || gr > 10) {
        setCgpaError("Each course grade must be between 0.0 and 10.0.");
        return;
      }
    }

    setCgpaLoading(true);
    try {
      const res = await submitContractTask(
        buildLightCgpaRequest("public-web-client", courses)
      );
      setCgpaResult(res);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCgpaError("Test finishing, try again in a few seconds.");
      } else {
        setCgpaError(err instanceof Error ? err.message : "CGPA computation failed");
      }
    } finally {
      setCgpaLoading(false);
    }
  };

  const handleRunHash = async () => {
    const iters = Number(hashIterations);
    if (!Number.isFinite(iters) || iters < 1 || iters > 1000000) {
      setHashError("Iterations must be between 1 and 1,000,000.");
      return;
    }

    setHashLoading(true);
    setHashError(null);
    try {
      const res = await submitContractTask(
        buildHeavyHashRequest("public-web-client", hashInput, iters)
      );
      setHashResult(res);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setHashError("Test finishing, try again in a few seconds.");
      } else {
        setHashError(
          err instanceof Error ? err.message : "Heavy hashing computation failed"
        );
      }
    } finally {
      setHashLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FAF7F2] text-[#1C1917] flex flex-col font-sans">
      {/* Client-only Top Header (zero Admin routes or CSV exports exposed) */}
      <header className="border-b border-[#E5DFD3] bg-white/95 backdrop-blur sticky top-0 z-30">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-3.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-[#E8F3F5] border border-[#B8DCE3] flex items-center justify-center text-[#0F5C6E]">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-base tracking-tight text-[#1C1917]">
                  Cloud<span className="text-[#0F5C6E]">Balance</span>
                </span>
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-md bg-[#F3EFE6] text-[#57534E] border border-[#E5DFD3]">
                  Client Portal
                </span>
              </div>
              <p className="text-xs text-[#78716C] hidden sm:block">
                Distributed Task Execution &amp; Latency Monitor
              </p>
            </div>
          </div>

          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[#15803D] bg-[#DCFCE7] border border-[#BBF7D0] px-2.5 py-1 rounded-full">
            <span className="h-1.5 w-1.5 rounded-full bg-[#16A34A]" />
            Cluster Accepting Tasks
          </span>
        </div>
      </header>

      {/* Main Client Workbench */}
      <main className="flex-1 max-w-4xl w-full mx-auto px-4 sm:px-6 py-7 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-[#1C1917] tracking-tight">
              Real-Time Cluster Workload Portal
            </h1>
            <p className="text-sm text-[#57534E] mt-1">
              Submit lightweight or CPU-intensive jobs to the CloudBalance cluster and
              inspect execution timing.
            </p>
          </div>
        </div>

        {/* Workload Selector Tabs */}
        <div className="grid grid-cols-2 gap-1.5 bg-[#F3EFE6] p-1 rounded-xl border border-[#E5DFD3]">
          <button
            type="button"
            onClick={() => setActiveTab("cgpa")}
            className={`min-h-[42px] py-2 px-4 rounded-lg text-xs sm:text-sm font-medium flex items-center justify-center gap-2 transition-colors ${activeTab === "cgpa"
                ? "bg-white text-[#0F5C6E] border border-[#E5DFD3] shadow-xs font-semibold"
                : "text-[#57534E] hover:text-[#1C1917]"
              }`}
          >
            <Calculator className="w-4 h-4" />
            <span>Lightweight CGPA Tool</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("hash")}
            className={`min-h-[42px] py-2 px-4 rounded-lg text-xs sm:text-sm font-medium flex items-center justify-center gap-2 transition-colors ${activeTab === "hash"
                ? "bg-white text-[#0F5C6E] border border-[#E5DFD3] shadow-xs font-semibold"
                : "text-[#57534E] hover:text-[#1C1917]"
              }`}
          >
            <Hash className="w-4 h-4" />
            <span>Heavy SHA-256 Hashing</span>
          </button>
        </div>

        {/* Tab 1: CGPA Calculator */}
        {activeTab === "cgpa" && (
          <section className="bg-white border border-[#E5DFD3] rounded-2xl p-5 sm:p-6 space-y-5 shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#EFEAE0] pb-3.5">
              <div>
                <h2 className="text-base font-semibold text-[#1C1917] flex items-center gap-2">
                  <Calculator className="w-4 h-4 text-[#0F5C6E]" />
                  Cumulative Grade Point Average (CGPA) Calculator
                </h2>
                <p className="text-xs text-[#78716C] mt-0.5">
                  Lightweight workload dispatched to an available compute worker.
                </p>
              </div>
              <button
                type="button"
                onClick={handleAddCourse}
                className="min-h-[38px] px-3 py-1.5 rounded-lg text-xs font-medium bg-[#FAF7F2] hover:bg-[#F3EFE6] text-[#0F5C6E] border border-[#D6CFC2] flex items-center gap-1.5 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Course
              </button>
            </div>

            <div className="space-y-2.5">
              {courses.map((course, idx) => (
                <div
                  key={course.id}
                  className="grid grid-cols-12 gap-2.5 items-center bg-[#FAF7F2] p-3 rounded-xl border border-[#EFEAE0]"
                >
                  <div className="col-span-12 sm:col-span-6">
                    <label className="text-[11px] font-medium text-[#57534E] block mb-1">
                      Course Name #{idx + 1}
                    </label>
                    <input
                      type="text"
                      value={course.name}
                      onChange={(e) =>
                        handleUpdateCourse(course.id, "name", e.target.value)
                      }
                      className="w-full min-h-[38px] bg-white border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs text-[#1C1917] focus:outline-none focus:border-[#0F5C6E] focus:ring-2 focus:ring-[#0F5C6E]/15"
                    />
                  </div>

                  <div className="col-span-5 sm:col-span-2">
                    <label className="text-[11px] font-medium text-[#57534E] block mb-1">
                      Credits
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      min="1"
                      max="10"
                      value={course.credits}
                      onChange={(e) =>
                        handleUpdateCourse(course.id, "credits", e.target.value)
                      }
                      className="w-full min-h-[38px] bg-white border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs text-[#1C1917] tabular-nums focus:outline-none focus:border-[#0F5C6E] focus:ring-2 focus:ring-[#0F5C6E]/15"
                    />
                  </div>

                  <div className="col-span-5 sm:col-span-3">
                    <label className="text-[11px] font-medium text-[#57534E] block mb-1">
                      Grade (0–10)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="10"
                      value={course.grade}
                      onChange={(e) =>
                        handleUpdateCourse(course.id, "grade", e.target.value)
                      }
                      className="w-full min-h-[38px] bg-white border border-[#D6CFC2] rounded-lg px-2.5 py-1.5 text-xs text-[#1C1917] tabular-nums focus:outline-none focus:border-[#0F5C6E] focus:ring-2 focus:ring-[#0F5C6E]/15"
                    />
                  </div>

                  <div className="col-span-2 sm:col-span-1 flex items-end justify-center pt-5 sm:pt-4">
                    <button
                      type="button"
                      onClick={() => handleRemoveCourse(course.id)}
                      disabled={courses.length <= 1}
                      className="h-9 w-9 inline-flex items-center justify-center rounded-lg text-[#78716C] hover:text-[#B91C1C] hover:bg-[#FEE2E2]/60 disabled:opacity-30 transition-colors"
                      title="Remove Course"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={handleRunCgpa}
              disabled={cgpaLoading}
              className="w-full min-h-[44px] py-2.5 px-4 rounded-xl font-medium text-sm bg-[#0F5C6E] hover:bg-[#0B4857] disabled:bg-[#D6CFC2] disabled:text-[#78716C] text-white flex items-center justify-center gap-2 transition-colors shadow-xs"
            >
              {cgpaLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Computing on Worker Cluster...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>Dispatch &amp; Calculate CGPA</span>
                </>
              )}
            </button>

            {cgpaError && (
              <div
                role="alert"
                className="p-3 rounded-xl bg-[#FEE2E2] border border-[#FECACA] text-[#B91C1C] text-xs font-medium flex items-center gap-2"
              >
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{cgpaError}</span>
              </div>
            )}

            {cgpaResult &&
              (() => {
                const rStatus = String(cgpaResult.result?.status || "");
                const isFailure =
                  Boolean(cgpaResult.result?.error) ||
                  ["unavailable", "rejected_503", "timeout", "error"].includes(
                    rStatus
                  );
                return (
                  <div
                    className={`mt-2 p-5 rounded-xl bg-[#FAF7F2] border space-y-4 ${isFailure ? "border-[#F59E0B]" : "border-[#BBF7D0]"
                      }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E5DFD3] pb-3">
                      <div className="flex items-center gap-2">
                        {isFailure ? (
                          <AlertCircle className="w-5 h-5 text-[#B45309]" />
                        ) : (
                          <CheckCircle2 className="w-5 h-5 text-[#15803D]" />
                        )}
                        <span className="text-sm sm:text-base font-semibold text-[#1C1917] tabular-nums">
                          Served by{" "}
                          <span className="text-[#0F5C6E] font-mono">
                            {cgpaResult.assigned_worker}
                          </span>{" "}
                          in{" "}
                          <span className="text-[#15803D]">
                            {cgpaResult.total_ms.toFixed(1)} ms
                          </span>
                        </span>
                      </div>
                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-mono font-medium ${isFailure
                            ? "bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]"
                            : "bg-[#DCFCE7] text-[#15803D] border border-[#BBF7D0]"
                          }`}
                      >
                        {rStatus === "unavailable"
                          ? "Worker Offline"
                          : isFailure
                            ? rStatus || "Error"
                            : "200 OK"}
                      </span>
                    </div>

                    {(cgpaResult.result?.error || cgpaResult.result?.detail) && (
                      <div className="p-3 rounded-xl bg-[#FEE2E2] border border-[#FECACA] text-xs text-[#B91C1C] font-mono">
                        {String(
                          cgpaResult.result?.error ?? cgpaResult.result?.detail
                        )}
                      </div>
                    )}

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Calculated CGPA
                        </span>
                        <span className="text-xl font-semibold text-[#0F5C6E] mt-0.5 block tabular-nums">
                          {cgpaResult.result?.cgpa ?? "N/A"}{" "}
                          <span className="text-xs font-normal text-[#78716C]">
                            / 10.0
                          </span>
                        </span>
                      </div>

                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Total Credits
                        </span>
                        <span className="text-xl font-semibold text-[#1C1917] mt-0.5 block tabular-nums">
                          {cgpaResult.result?.total_credits ?? "N/A"}
                        </span>
                      </div>

                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Queue Delay
                        </span>
                        <span className="text-xl font-semibold text-[#B45309] mt-0.5 block tabular-nums">
                          {cgpaResult.queue_ms.toFixed(2)}{" "}
                          <span className="text-xs font-normal text-[#78716C]">
                            ms
                          </span>
                        </span>
                      </div>

                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Execution Time
                        </span>
                        <span className="text-xl font-semibold text-[#15803D] mt-0.5 block tabular-nums">
                          {cgpaResult.exec_ms.toFixed(2)}{" "}
                          <span className="text-xs font-normal text-[#78716C]">
                            ms
                          </span>
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })()}
          </section>
        )}

        {/* Tab 2: Heavy Hashing */}
        {activeTab === "hash" && (
          <section className="bg-white border border-[#E5DFD3] rounded-2xl p-5 sm:p-6 space-y-5 shadow-xs">
            <div className="border-b border-[#EFEAE0] pb-3.5">
              <h2 className="text-base font-semibold text-[#1C1917] flex items-center gap-2">
                <Hash className="w-4 h-4 text-[#0F5C6E]" />
                Heavy Workload: SHA-256 Iterative Hashing Loop
              </h2>
              <p className="text-xs text-[#78716C] mt-0.5">
                CPU-intensive benchmark task tuned for 0.5–1.0s execution time per
                worker.
              </p>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium text-[#44403C] block mb-1.5">
                  Input Seed Payload String
                </label>
                <input
                  type="text"
                  value={hashInput}
                  onChange={(e) => setHashInput(e.target.value)}
                  className="w-full min-h-[42px] bg-[#FAF7F2] border border-[#D6CFC2] rounded-xl px-3 py-2 text-sm text-[#1C1917] focus:outline-none focus:border-[#0F5C6E] focus:ring-2 focus:ring-[#0F5C6E]/15 font-mono"
                  placeholder="Enter text string to digest..."
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-medium text-[#44403C]">
                    Iteration Count (Loop Intensity)
                  </label>
                  <span className="text-xs font-mono text-[#0F5C6E] font-semibold tabular-nums">
                    {hashIterations.toLocaleString()} iterations
                  </span>
                </div>

                <div className="flex flex-wrap gap-2 mb-2.5">
                  {[50000, 150000, 300000, 500000].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setHashIterations(preset)}
                      className={`min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono border transition-colors tabular-nums ${hashIterations === preset
                          ? "bg-[#E8F3F5] text-[#0F5C6E] border-[#B8DCE3] font-semibold"
                          : "bg-[#FAF7F2] text-[#57534E] border-[#E5DFD3] hover:text-[#1C1917]"
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
                  className="w-full accent-[#0F5C6E] h-1.5 bg-[#E5DFD3] rounded-lg cursor-pointer"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={handleRunHash}
              disabled={hashLoading}
              className="w-full min-h-[44px] py-2.5 px-4 rounded-xl font-medium text-sm bg-[#0F5C6E] hover:bg-[#0B4857] disabled:bg-[#D6CFC2] disabled:text-[#78716C] text-white flex items-center justify-center gap-2 transition-colors shadow-xs"
            >
              {hashLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Computing Iterative Hashing on Worker...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>Dispatch &amp; Run Heavy Hash</span>
                </>
              )}
            </button>

            {hashError && (
              <div
                role="alert"
                className="p-3 rounded-xl bg-[#FEE2E2] border border-[#FECACA] text-[#B91C1C] text-xs font-medium flex items-center gap-2"
              >
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{hashError}</span>
              </div>
            )}

            {hashResult &&
              (() => {
                const rStatus = String(hashResult.result?.status || "");
                const isFailure =
                  Boolean(hashResult.result?.error) ||
                  ["unavailable", "rejected_503", "timeout", "error"].includes(
                    rStatus
                  );
                return (
                  <div
                    className={`mt-2 p-5 rounded-xl bg-[#FAF7F2] border space-y-4 ${isFailure ? "border-[#F59E0B]" : "border-[#BBF7D0]"
                      }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E5DFD3] pb-3">
                      <div className="flex items-center gap-2">
                        {isFailure ? (
                          <AlertCircle className="w-5 h-5 text-[#B45309]" />
                        ) : (
                          <CheckCircle2 className="w-5 h-5 text-[#15803D]" />
                        )}
                        <span className="text-sm sm:text-base font-semibold text-[#1C1917] tabular-nums">
                          Served by{" "}
                          <span className="text-[#0F5C6E] font-mono">
                            {hashResult.assigned_worker}
                          </span>{" "}
                          in{" "}
                          <span className="text-[#15803D]">
                            {hashResult.total_ms.toFixed(1)} ms
                          </span>
                        </span>
                      </div>
                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-mono font-medium ${isFailure
                            ? "bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]"
                            : "bg-[#DCFCE7] text-[#15803D] border border-[#BBF7D0]"
                          }`}
                      >
                        {rStatus === "unavailable"
                          ? "Worker Offline"
                          : isFailure
                            ? rStatus || "Error"
                            : "200 OK"}
                      </span>
                    </div>

                    <div className="bg-white p-3 rounded-xl border border-[#E5DFD3] space-y-1">
                      <span className="text-[11px] font-medium text-[#78716C] block">
                        Final SHA-256 Digest Hex
                      </span>
                      <p className="text-xs font-mono text-[#0F5C6E] break-all select-all">
                        {hashResult.result?.final_hash ??
                          hashResult.result?.detail ??
                          hashResult.result?.error ??
                          "N/A"}
                      </p>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Iterations Run
                        </span>
                        <span className="text-lg font-semibold text-[#1C1917] mt-0.5 block tabular-nums">
                          {hashResult.result?.iterations?.toLocaleString() ??
                            hashIterations.toLocaleString()}
                        </span>
                      </div>

                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Queue Delay
                        </span>
                        <span className="text-lg font-semibold text-[#B45309] mt-0.5 block tabular-nums">
                          {hashResult.queue_ms.toFixed(2)}{" "}
                          <span className="text-xs font-normal text-[#78716C]">
                            ms
                          </span>
                        </span>
                      </div>

                      <div className="bg-white p-3 rounded-xl border border-[#E5DFD3]">
                        <span className="text-[11px] font-medium text-[#78716C] block">
                          Execution Time
                        </span>
                        <span className="text-lg font-semibold text-[#15803D] mt-0.5 block tabular-nums">
                          {hashResult.exec_ms.toFixed(2)}{" "}
                          <span className="text-xs font-normal text-[#78716C]">
                            ms
                          </span>
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })()}
          </section>
        )}
      </main>
    </div>
  );
};

export default PublicTasksPage;
