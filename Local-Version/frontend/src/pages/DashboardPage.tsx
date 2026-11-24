import React from "react";
import { BenchmarkSection } from "../components/BenchmarkSection";
import { Header } from "../components/Header";
import { useWebSocket } from "../hooks/useWebSocket";

export const DashboardPage: React.FC = () => {
  const { snapshot, connectionState, isStale, error } = useWebSocket();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        snapshot={snapshot}
        connectionState={connectionState}
        isStale={isStale}
      />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 py-5 space-y-5">
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-rose-500/15 border border-rose-500/40 px-4 py-2.5 text-xs text-rose-200"
          >
            {error}
          </div>
        )}

        <BenchmarkSection />
      </main>
    </div>
  );
};

export default DashboardPage;
