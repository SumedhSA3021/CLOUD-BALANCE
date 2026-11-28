import React from "react";
import { Download } from "lucide-react";
import type { TestSummaryRow } from "../lib/api";

interface SummaryComparisonPanelProps {
  summaryRows: TestSummaryRow[];
  summaryError: string | null;
  onRefresh: () => void;
  onDownload: (file: "summary" | "log") => void;
  showDownloads?: boolean;
}

const calcDiffPct = (milpVal: number, rrVal: number): number => {
  if (!rrVal || Number.isNaN(rrVal)) return 0;
  return ((milpVal - rrVal) / rrVal) * 100;
};

export const SummaryComparisonPanel: React.FC<SummaryComparisonPanelProps> = ({
  summaryRows,
  summaryError,
  onRefresh,
  onDownload,
  showDownloads = true,
}) => {
  const latestMilpSummary = summaryRows
    .slice()
    .reverse()
    .find((r) => {
      const m = r.mode?.toLowerCase();
      return m === "milp" || m === "ortools_milp";
    });
  const latestRrSummary = summaryRows
    .slice()
    .reverse()
    .find((r) => {
      const m = r.mode?.toLowerCase();
      return m === "round_robin" || m === "rr";
    });

  return (
    <section
      aria-label="Test Results Comparison"
      className="p-5 rounded-2xl bg-white border border-[#E5DFD3] shadow-xs space-y-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[#1C1917]">
            Benchmark Results &amp; Comparison
          </h3>
          <p className="text-xs text-[#78716C] mt-0.5">
            Live test results from test_summary.csv comparing OR-Tools MILP vs
            Round Robin with difference %.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono bg-[#FAF7F2] hover:bg-[#F3EFE6] text-[#44403C] border border-[#D6CFC2] transition-colors"
          >
            Refresh
          </button>
          {showDownloads && (
            <>
              <button
                type="button"
                onClick={() => onDownload("summary")}
                className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono bg-[#FAF7F2] hover:bg-[#E8F3F5] text-[#0F5C6E] border border-[#D6CFC2] hover:border-[#B8DCE3] flex items-center gap-1.5 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span>test_summary.csv</span>
              </button>
              <button
                type="button"
                onClick={() => onDownload("log")}
                className="min-h-[34px] px-3 py-1 rounded-lg text-xs font-mono bg-[#FAF7F2] hover:bg-[#E8F3F5] text-[#0F5C6E] border border-[#D6CFC2] hover:border-[#B8DCE3] flex items-center gap-1.5 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span>test_log.csv</span>
              </button>
            </>
          )}
        </div>
      </div>

      {summaryError ? (
        <div
          role="alert"
          className="p-4 text-center text-xs text-[#B91C1C] rounded-xl bg-[#FEE2E2] border border-[#FECACA]"
        >
          Could not load test summaries: {summaryError}
        </div>
      ) : summaryRows.length === 0 ? (
        <div className="p-8 text-center text-xs text-[#78716C] rounded-xl bg-[#FAF7F2] border border-dashed border-[#D6CFC2]">
          No completed tests yet
        </div>
      ) : (
        <div className="space-y-5">
          {latestMilpSummary && latestRrSummary ? (
            <div className="overflow-x-auto border border-[#E5DFD3] rounded-xl">
              <table className="w-full text-left text-xs font-mono border-collapse tabular-nums">
                <thead>
                  <tr className="border-b border-[#E5DFD3] text-[#57534E] bg-[#F3EFE6]">
                    <th className="py-2.5 px-3">Metric</th>
                    <th className="py-2.5 px-3 text-[#0F5C6E] font-semibold">
                      OR-Tools MILP
                    </th>
                    <th className="py-2.5 px-3 text-[#B45309] font-semibold">
                      Round Robin
                    </th>
                    <th className="py-2.5 px-3">Difference %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EFEAE0]">
                  <tr>
                    <td className="py-2.5 px-3 font-medium text-[#44403C]">
                      Avg Latency (avg_ms)
                    </td>
                    <td className="py-2.5 px-3 text-[#1C1917] font-semibold">
                      {Number(latestMilpSummary.avg_ms).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3 text-[#57534E]">
                      {Number(latestRrSummary.avg_ms).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(
                          Number(latestMilpSummary.avg_ms),
                          Number(latestRrSummary.avg_ms)
                        );
                        const isBetter = diff <= 0;
                        return (
                          <span
                            className={`font-semibold ${
                              isBetter ? "text-[#15803D]" : "text-[#B91C1C]"
                            }`}
                          >
                            {diff > 0
                              ? `+${diff.toFixed(1)}%`
                              : `${diff.toFixed(1)}%`}{" "}
                            {isBetter ? "(Faster)" : ""}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>

                  <tr>
                    <td className="py-2.5 px-3 font-medium text-[#44403C]">
                      P95 Latency (p95_ms)
                    </td>
                    <td className="py-2.5 px-3 text-[#1C1917] font-semibold">
                      {Number(latestMilpSummary.p95_ms).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3 text-[#57534E]">
                      {Number(latestRrSummary.p95_ms).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(
                          Number(latestMilpSummary.p95_ms),
                          Number(latestRrSummary.p95_ms)
                        );
                        const isBetter = diff <= 0;
                        return (
                          <span
                            className={`font-semibold ${
                              isBetter ? "text-[#15803D]" : "text-[#B91C1C]"
                            }`}
                          >
                            {diff > 0
                              ? `+${diff.toFixed(1)}%`
                              : `${diff.toFixed(1)}%`}{" "}
                            {isBetter ? "(Lower Tail Latency)" : ""}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>

                  <tr>
                    <td className="py-2.5 px-3 font-medium text-[#44403C]">
                      Failed Requests (failed)
                    </td>
                    <td className="py-2.5 px-3 text-[#1C1917] font-semibold">
                      {latestMilpSummary.failed}
                    </td>
                    <td className="py-2.5 px-3 text-[#57534E]">
                      {latestRrSummary.failed}
                    </td>
                    <td className="py-2.5 px-3">
                      {Number(latestMilpSummary.failed) <=
                      Number(latestRrSummary.failed) ? (
                        <span className="text-[#15803D] font-semibold">
                          -
                          {Number(latestRrSummary.failed) -
                            Number(latestMilpSummary.failed)}{" "}
                          fewer failures
                        </span>
                      ) : (
                        <span className="text-[#B91C1C] font-semibold">
                          +
                          {Number(latestMilpSummary.failed) -
                            Number(latestRrSummary.failed)}{" "}
                          failures
                        </span>
                      )}
                    </td>
                  </tr>

                  <tr>
                    <td className="py-2.5 px-3 font-medium text-[#44403C]">
                      Busy-Time Std-Dev (busy_time_stddev)
                    </td>
                    <td className="py-2.5 px-3 text-[#1C1917] font-semibold">
                      {Number(latestMilpSummary.busy_time_stddev).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3 text-[#57534E]">
                      {Number(latestRrSummary.busy_time_stddev).toFixed(2)} ms
                    </td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(
                          Number(latestMilpSummary.busy_time_stddev),
                          Number(latestRrSummary.busy_time_stddev)
                        );
                        const isBetter = diff <= 0;
                        return (
                          <span
                            className={`font-semibold ${
                              isBetter ? "text-[#15803D]" : "text-[#B45309]"
                            }`}
                          >
                            {diff > 0
                              ? `+${diff.toFixed(1)}%`
                              : `${diff.toFixed(1)}%`}{" "}
                            {isBetter ? "(Fairer Distribution)" : ""}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>

                  <tr>
                    <td className="py-2.5 px-3 font-medium text-[#44403C]">
                      Throughput (throughput_rps)
                    </td>
                    <td className="py-2.5 px-3 text-[#1C1917] font-semibold">
                      {Number(latestMilpSummary.throughput_rps).toFixed(2)} req/s
                    </td>
                    <td className="py-2.5 px-3 text-[#57534E]">
                      {Number(latestRrSummary.throughput_rps).toFixed(2)} req/s
                    </td>
                    <td className="py-2.5 px-3">
                      {(() => {
                        const diff = calcDiffPct(
                          Number(latestMilpSummary.throughput_rps),
                          Number(latestRrSummary.throughput_rps)
                        );
                        return (
                          <span className="text-[#44403C] font-semibold">
                            {diff > 0
                              ? `+${diff.toFixed(1)}%`
                              : `${diff.toFixed(1)}%`}
                          </span>
                        );
                      })()}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="space-y-2">
            <h4 className="text-xs font-medium uppercase text-[#57534E] tracking-wider">
              All Completed Test Summaries ({summaryRows.length} runs)
            </h4>
            <div className="overflow-x-auto border border-[#E5DFD3] rounded-xl">
              <table className="w-full text-left text-xs font-mono border-collapse tabular-nums">
                <thead>
                  <tr className="bg-[#F3EFE6] text-[#57534E] border-b border-[#E5DFD3]">
                    <th className="py-2 px-3">Test ID</th>
                    <th className="py-2 px-3">Mode</th>
                    <th className="py-2 px-3">Duration</th>
                    <th className="py-2 px-3">Reqs</th>
                    <th className="py-2 px-3">Failed</th>
                    <th className="py-2 px-3">Clients Seen</th>
                    <th className="py-2 px-3">Avg Latency</th>
                    <th className="py-2 px-3">P95 Latency</th>
                    <th className="py-2 px-3">Busy StdDev</th>
                    <th className="py-2 px-3">Throughput</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EFEAE0]">
                  {summaryRows.map((r, i) => (
                    <tr key={r.test_id || i} className="hover:bg-[#FAF7F2] transition-colors">
                      <td className="py-2 px-3 text-[#0F5C6E] font-medium">
                        {r.test_id}
                      </td>
                      <td className="py-2 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                            r.mode === "milp" || r.mode === "ortools_milp"
                              ? "bg-[#E8F3F5] text-[#0F5C6E] border border-[#B8DCE3]"
                              : "bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]"
                          }`}
                        >
                          {r.mode}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-[#57534E]">{r.duration_s}s</td>
                      <td className="py-2 px-3 text-[#1C1917] font-semibold">
                        {r.requests}
                      </td>
                      <td
                        className={`py-2 px-3 ${
                          Number(r.failed) > 0
                            ? "text-[#B91C1C] font-semibold"
                            : "text-[#15803D]"
                        }`}
                      >
                        {r.failed}
                      </td>
                      <td className="py-2 px-3 text-[#57534E]">
                        {r.clients_seen && r.clients_seen !== "" ? r.clients_seen : "—"}
                      </td>
                      <td className="py-2 px-3 text-[#1C1917]">
                        {Number(r.avg_ms).toFixed(1)} ms
                      </td>
                      <td className="py-2 px-3 text-[#1C1917]">
                        {Number(r.p95_ms).toFixed(1)} ms
                      </td>
                      <td className="py-2 px-3 text-[#1C1917]">
                        {Number(r.busy_time_stddev).toFixed(1)} ms
                      </td>
                      <td className="py-2 px-3 text-[#57534E]">
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
    </section>
  );
};
