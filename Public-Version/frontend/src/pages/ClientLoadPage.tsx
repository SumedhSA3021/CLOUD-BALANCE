import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Play,
  Square,
} from "lucide-react";
import {
  ApiError,
  fetchTestStatus,
  submitContractTask,
  type TestStatusResponse,
} from "../lib/api";
import {
  buildHeavyHashRequest,
  buildLightCgpaRequest,
  DEFAULT_CGPA_COURSES,
  DEFAULT_HASH_INPUT,
  DEFAULT_HASH_ITERATIONS,
} from "../lib/taskPayloads";

const STORAGE_CLIENT_ID_KEY = "cloudbalance_client_id";
const MIN_RATE = 0.5;
const MAX_RATE = 10;

export function sampleExponentialGapMs(
  ratePerSec: number,
  rand: () => number = Math.random
): number {
  const safeU = Math.min(1 - 1e-12, Math.max(0, rand()));
  return (-Math.log(Math.max(1e-12, 1 - safeU)) / ratePerSec) * 1000;
}

function resolveClientId(search: string): string {
  const params = new URLSearchParams(search);
  const queryId = params.get("id")?.trim();
  if (queryId) {
    return queryId.slice(0, 64);
  }
  try {
    const stored = window.localStorage.getItem(STORAGE_CLIENT_ID_KEY)?.trim();
    if (stored) {
      return stored.slice(0, 64);
    }
    const generated = `client-${Math.random().toString(16).slice(2, 6).padEnd(4, "0")}`;
    window.localStorage.setItem(STORAGE_CLIENT_ID_KEY, generated);
    return generated;
  } catch {
    return `client-${Math.random().toString(16).slice(2, 6).padEnd(4, "0")}`;
  }
}

export const ClientLoadPage: React.FC = () => {
  const clientId = useMemo(
    () =>
      typeof window !== "undefined"
        ? resolveClientId(window.location.search)
        : "client-0000",
    []
  );

  const [rateInput, setRateInput] = useState<string>("3");
  const [taskType, setTaskType] = useState<"light" | "heavy">("light");
  const [running, setRunning] = useState<boolean>(false);

  const [sent, setSent] = useState<number>(0);
  const [ok, setOk] = useState<number>(0);
  const [failed, setFailed] = useState<number>(0);
  const [latencySumMs, setLatencySumMs] = useState<number>(0);
  const [lastWorker, setLastWorker] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number>(0);

  const [validationError, setValidationError] = useState<string | null>(null);
  const [drainNotice, setDrainNotice] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<TestStatusResponse | null>(null);

  const runningRef = useRef<boolean>(false);
  const timerRef = useRef<number | null>(null);
  const tickIntervalRef = useRef<number | null>(null);
  const startTimeRef = useRef<number>(0);
  const runEpochRef = useRef<number>(0);

  const parsedRate = Number(rateInput);
  const isRateValid =
    Number.isFinite(parsedRate) && parsedRate >= MIN_RATE && parsedRate <= MAX_RATE;

  const clearTimers = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (tickIntervalRef.current !== null) {
      window.clearInterval(tickIntervalRef.current);
      tickIntervalRef.current = null;
    }
  }, []);

  const stopLoop = useCallback(() => {
    runningRef.current = false;
    runEpochRef.current += 1;
    clearTimers();
    if (startTimeRef.current > 0) {
      setElapsedMs(Math.max(0, Date.now() - startTimeRef.current));
    }
    setRunning(false);
  }, [clearTimers]);

  useEffect(() => {
    return () => {
      runningRef.current = false;
      clearTimers();
    };
  }, [clearTimers]);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetchTestStatus();
        if (active) {
          setTestStatus(res);
        }
      } catch {
        // Non-fatal: controller may be restarting or unreachable briefly
      }
    };
    void poll();
    const id = window.setInterval(() => {
      void poll();
    }, 2000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  const dispatchSingleTask = useCallback(
    async (rate: number, selectedType: "light" | "heavy", epoch: number) => {
      const sentAtSec = Date.now() / 1000;
      const requestBody =
        selectedType === "heavy"
          ? buildHeavyHashRequest(
              clientId,
              DEFAULT_HASH_INPUT,
              DEFAULT_HASH_ITERATIONS,
              {
                sent_at: sentAtSec,
                client_rate: rate,
                client_task_type: "heavy",
              }
            )
          : buildLightCgpaRequest(clientId, DEFAULT_CGPA_COURSES, {
              sent_at: sentAtSec,
              client_rate: rate,
              client_task_type: "light",
            });

      setSent((prev) => prev + 1);
      try {
        const res = await submitContractTask(requestBody);
        if (runEpochRef.current !== epoch) return;
        setOk((prev) => prev + 1);
        setLatencySumMs((prev) => prev + res.total_ms);
        setLastWorker(res.assigned_worker);
        setDrainNotice(null);
        setLastError(null);
      } catch (err) {
        if (runEpochRef.current !== epoch) return;
        setFailed((prev) => prev + 1);
        if (err instanceof ApiError && err.status === 409) {
          setDrainNotice("Test finishing, try again in a few seconds.");
        } else {
          setLastError(
            err instanceof Error ? err.message : "Task request failed"
          );
        }
      }
    },
    [clientId]
  );

  const handleStart = () => {
    if (runningRef.current) return;
    if (!isRateValid) {
      setValidationError(
        `Tasks per second must be between ${MIN_RATE} and ${MAX_RATE}.`
      );
      return;
    }

    setValidationError(null);
    setDrainNotice(null);
    setLastError(null);
    setSent(0);
    setOk(0);
    setFailed(0);
    setLatencySumMs(0);
    setLastWorker(null);
    setElapsedMs(0);

    const rate = parsedRate;
    const selectedType = taskType;
    const epoch = runEpochRef.current + 1;
    runEpochRef.current = epoch;
    runningRef.current = true;
    startTimeRef.current = Date.now();
    setRunning(true);

    tickIntervalRef.current = window.setInterval(() => {
      if (!runningRef.current) return;
      setElapsedMs(Math.max(0, Date.now() - startTimeRef.current));
    }, 250);

    const scheduleNext = () => {
      if (!runningRef.current || runEpochRef.current !== epoch) return;
      const gapMs = sampleExponentialGapMs(rate);
      timerRef.current = window.setTimeout(() => {
        if (!runningRef.current || runEpochRef.current !== epoch) return;
        scheduleNext();
        void dispatchSingleTask(rate, selectedType, epoch);
      }, gapMs);
    };

    scheduleNext();
  };

  const elapsedSec = elapsedMs / 1000;
  const achievedRate = elapsedSec > 0 ? sent / elapsedSec : 0;
  const avgLatencyMs = ok > 0 ? latencySumMs / ok : 0;

  return (
    <div className="min-h-screen bg-[#FAF7F2] text-[#1C1917] flex flex-col font-sans">
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
                  Client Load Generator
                </span>
              </div>
              <p className="text-xs text-[#78716C]">
                Public Browser Poisson Traffic Client
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="px-2.5 py-1 rounded-md bg-[#F3EFE6] border border-[#E5DFD3] text-[#57534E]">
              ID: <strong className="text-[#1C1917]">{clientId}</strong>
            </span>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-4xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        {/* Foreground Warning Banner */}
        <div className="bg-[#FEF3C7] border border-[#FDE68A] text-[#92400E] rounded-xl px-4 py-3 text-sm flex items-center gap-2.5">
          <AlertTriangle className="w-4 h-4 shrink-0 text-[#B45309]" />
          <span>
            <strong>Keep this tab in the foreground</strong> while generating load —
            browsers throttle background timers.
          </span>
        </div>

        {/* Benchmark / Test Status Banner */}
        <section className="bg-white border border-[#E5DFD3] rounded-2xl p-4 shadow-sm flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 text-sm">
            <Activity className="w-4 h-4 text-[#0F5C6E]" />
            <span className="font-medium text-[#1C1917]">Cluster Test Status:</span>
            <span
              data-testid="client-test-state"
              className="px-2.5 py-0.5 rounded-md text-xs font-mono uppercase bg-[#F3EFE6] border border-[#E5DFD3] text-[#1C1917]"
            >
              {testStatus?.state ?? "unknown"}
            </span>
            <span className="text-xs text-[#57534E] font-mono">
              mode:{" "}
              <strong className="text-[#0F5C6E]" data-testid="client-test-mode">
                {testStatus?.mode ?? "—"}
              </strong>
            </span>
          </div>
          {testStatus?.test_id ? (
            <span className="text-xs font-mono text-[#78716C]">
              test_id: {testStatus.test_id}
            </span>
          ) : null}
        </section>

        {/* Controls Card */}
        <section className="bg-white border border-[#E5DFD3] rounded-2xl p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between gap-4 border-b border-[#EFEAE0] pb-4">
            <div>
              <h1 className="text-lg font-semibold text-[#1C1917]">
                Poisson Traffic Controls
              </h1>
              <p className="text-xs text-[#78716C]">
                Exponential inter-arrival gaps around your selected mean request rate.
              </p>
            </div>
            <span
              className={`px-2.5 py-1 rounded-full text-xs font-medium border ${
                running
                  ? "bg-[#DCFCE7] border-[#BBF7D0] text-[#15803D]"
                  : "bg-[#F3EFE6] border-[#E5DFD3] text-[#57534E]"
              }`}
            >
              {running ? "Streaming" : "Stopped"}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="client-rate-input"
                className="block text-xs font-medium uppercase tracking-wider text-[#57534E] mb-1.5"
              >
                Tasks per second (0.5 – 10)
              </label>
              <input
                id="client-rate-input"
                type="number"
                min={MIN_RATE}
                max={MAX_RATE}
                step={0.5}
                value={rateInput}
                disabled={running}
                onChange={(e) => {
                  setRateInput(e.target.value);
                  setValidationError(null);
                }}
                className="w-full rounded-xl border border-[#D6CFC2] bg-[#FAF7F2] px-3.5 py-2.5 text-sm font-mono text-[#1C1917] focus:outline-none focus:ring-2 focus:ring-[#0F5C6E] disabled:opacity-60 disabled:cursor-not-allowed"
              />
            </div>

            <div>
              <label
                htmlFor="client-task-type-select"
                className="block text-xs font-medium uppercase tracking-wider text-[#57534E] mb-1.5"
              >
                Task type
              </label>
              <select
                id="client-task-type-select"
                value={taskType}
                disabled={running}
                onChange={(e) =>
                  setTaskType(e.target.value === "heavy" ? "heavy" : "light")
                }
                className="w-full rounded-xl border border-[#D6CFC2] bg-[#FAF7F2] px-3.5 py-2.5 text-sm text-[#1C1917] focus:outline-none focus:ring-2 focus:ring-[#0F5C6E] disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <option value="light">light (CGPA calculation)</option>
                <option value="heavy">heavy (SHA-256 hash)</option>
              </select>
            </div>
          </div>

          {validationError ? (
            <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-2.5 text-sm text-[#B91C1C] flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{validationError}</span>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button
              type="button"
              onClick={handleStart}
              disabled={running}
              className="inline-flex items-center gap-2 rounded-xl bg-[#0F5C6E] px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-[#0B4A59] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Play className="w-4 h-4" />
              Start Poisson
            </button>
            <button
              type="button"
              onClick={stopLoop}
              disabled={!running}
              className="inline-flex items-center gap-2 rounded-xl bg-[#B91C1C] px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-[#991B1B] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Square className="w-4 h-4" />
              Stop
            </button>
          </div>
        </section>

        {/* Draining / Error Notices */}
        {drainNotice ? (
          <div
            role="status"
            className="rounded-xl border border-[#FDE68A] bg-[#FEF3C7] px-4 py-3 text-sm text-[#92400E] flex items-center gap-2"
          >
            <AlertCircle className="w-4 h-4 shrink-0 text-[#B45309]" />
            <span>{drainNotice}</span>
          </div>
        ) : null}

        {lastError ? (
          <div
            role="alert"
            className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-sm text-[#B91C1C] flex items-center gap-2"
          >
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{lastError}</span>
          </div>
        ) : null}

        {/* Live Telemetry Counters */}
        <section className="bg-white border border-[#E5DFD3] rounded-2xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-[#EFEAE0] pb-3">
            <h2 className="text-sm font-semibold text-[#1C1917] flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-[#0F5C6E]" />
              Live Client Metrics
            </h2>
            <span className="text-xs font-mono text-[#78716C]">
              Declared: {isRateValid ? parsedRate.toFixed(1) : "—"} req/s · Type: {taskType}
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 font-mono tabular-nums">
            <div className="rounded-xl bg-[#FAF7F2] border border-[#E5DFD3] p-3">
              <div className="text-[11px] uppercase text-[#78716C]">Sent</div>
              <div className="text-lg font-semibold text-[#1C1917]" data-testid="client-sent">
                {sent}
              </div>
            </div>
            <div className="rounded-xl bg-[#FAF7F2] border border-[#E5DFD3] p-3">
              <div className="text-[11px] uppercase text-[#78716C]">OK</div>
              <div className="text-lg font-semibold text-[#15803D]" data-testid="client-ok">
                {ok}
              </div>
            </div>
            <div className="rounded-xl bg-[#FAF7F2] border border-[#E5DFD3] p-3">
              <div className="text-[11px] uppercase text-[#78716C]">Failed</div>
              <div className="text-lg font-semibold text-[#B91C1C]" data-testid="client-failed">
                {failed}
              </div>
            </div>
            <div className="rounded-xl bg-[#FAF7F2] border border-[#E5DFD3] p-3">
              <div className="text-[11px] uppercase text-[#78716C]">Achieved Rate</div>
              <div
                className="text-lg font-semibold text-[#0F5C6E]"
                data-testid="client-achieved-rate"
              >
                {achievedRate.toFixed(2)} rps
              </div>
            </div>
            <div className="rounded-xl bg-[#FAF7F2] border border-[#E5DFD3] p-3">
              <div className="text-[11px] uppercase text-[#78716C]">Avg Latency</div>
              <div className="text-lg font-semibold text-[#1C1917]" data-testid="client-avg-ms">
                {ok > 0 ? `${avgLatencyMs.toFixed(1)} ms` : "—"}
              </div>
            </div>
            <div className="rounded-xl bg-[#FAF7F2] border border-[#E5DFD3] p-3">
              <div className="text-[11px] uppercase text-[#78716C]">Last Worker</div>
              <div
                className="text-sm font-semibold text-[#1C1917] truncate pt-1"
                data-testid="client-last-worker"
              >
                {lastWorker ?? "—"}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};
