import React, { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, KeyRound, Lock, RefreshCw, ShieldCheck } from "lucide-react";
import { useAdminAuth } from "../context/AdminAuthContext";

interface AdminAuthGateProps {
  children: React.ReactNode;
}

export const AdminAuthGate: React.FC<AdminAuthGateProps> = ({ children }) => {
  const { status, token, login } = useAdminAuth();
  const [tokenInput, setTokenInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "checking") {
    return (
      <div className="min-h-screen bg-[#FAF7F2] text-[#1C1917] flex items-center justify-center p-6">
        <div className="bg-white border border-[#E5DFD3] rounded-2xl px-6 py-5 shadow-sm flex items-center gap-3 text-sm text-[#57534E]">
          <RefreshCw className="w-4 h-4 text-[#0F5C6E] animate-spin" />
          <span>Verifying Admin session...</span>
        </div>
      </div>
    );
  }

  if (status === "authenticated" && token) {
    return <>{children}</>;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = tokenInput.trim();
    if (!trimmed) {
      setError("Please enter your Admin token.");
      return;
    }

    setSubmitting(true);
    try {
      await login(trimmed);
      setTokenInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid admin credentials");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FAF7F2] text-[#1C1917] flex flex-col justify-center items-center px-4 py-10">
      <div className="w-full max-w-md bg-white border border-[#E5DFD3] rounded-2xl shadow-sm p-6 sm:p-8 space-y-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md bg-[#E8F3F5] border border-[#B8DCE3] text-[#0F5C6E] text-xs font-medium">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Restricted Operations</span>
            </div>
            <span className="text-xs font-mono text-[#78716C]">CLOUD BALANCE</span>
          </div>

          <h1 className="text-xl font-semibold tracking-tight text-[#1C1917] pt-1">
            Admin Access Required
          </h1>
          <p className="text-sm text-[#57534E] leading-relaxed">
            Restricted operations console. Enter your administrator bearer token
            to continue.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="admin-token-input"
              className="block text-xs font-medium text-[#44403C]"
            >
              Admin Token
            </label>
            <div className="relative">
              <KeyRound className="w-4 h-4 text-[#78716C] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                id="admin-token-input"
                type="password"
                autoComplete="current-password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Enter ADMIN_TOKEN"
                className="w-full pl-9 pr-3 py-2.5 min-h-[42px] bg-[#FAF7F2] border border-[#D6CFC2] rounded-xl text-sm text-[#1C1917] font-mono placeholder:text-[#A8A29E] focus:outline-none focus:border-[#0F5C6E] focus:ring-2 focus:ring-[#0F5C6E]/15 transition-colors"
              />
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="p-3 rounded-xl bg-[#FEE2E2] border border-[#FECACA] text-[#B91C1C] text-xs font-medium"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full min-h-[42px] px-4 py-2.5 rounded-xl bg-[#0F5C6E] hover:bg-[#0B4857] disabled:opacity-60 text-white text-sm font-medium flex items-center justify-center gap-2 transition-colors shadow-xs"
          >
            {submitting ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span>Verifying Token...</span>
              </>
            ) : (
              <>
                <Lock className="w-4 h-4" />
                <span>Sign In to Admin Panel</span>
              </>
            )}
          </button>
        </form>

        <div className="pt-4 border-t border-[#EFEAE0] flex items-center justify-between text-xs text-[#78716C]">
          <span>Clients can only submit workloads on the public portal.</span>
          <Link
            to="/"
            className="inline-flex items-center gap-1 font-medium text-[#0F5C6E] hover:text-[#0B4857] shrink-0"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Task Portal</span>
          </Link>
        </div>
      </div>
    </div>
  );
};
