import React from "react";
import { BenchmarkSection } from "../components/BenchmarkSection";
import { Header } from "../components/Header";
import { useAdminAuth } from "../context/AdminAuthContext";
import { useWebSocket } from "../hooks/useWebSocket";

export const DashboardPage: React.FC = () => {
  const { snapshot, connectionState, isStale, error } = useWebSocket();
  const { logout } = useAdminAuth();

  return (
    <div className="min-h-screen bg-[#FAF7F2] text-[#1C1917] flex flex-col font-sans">
      <Header
        mode="admin"
        snapshot={snapshot}
        connectionState={connectionState}
        isStale={isStale}
        onSignOut={logout}
      />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 py-5 space-y-5">
        {error && (
          <div
            role="alert"
            className="rounded-xl bg-[#FEE2E2] border border-[#FECACA] px-4 py-2.5 text-xs text-[#B91C1C]"
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
