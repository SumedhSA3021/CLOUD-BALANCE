import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { loginAdmin, verifyAdminSession } from "../lib/api";

export const ADMIN_TOKEN_STORAGE_KEY = "cb_admin_token";

export type AdminAuthStatus = "checking" | "unauthenticated" | "authenticated";

interface AdminAuthContextValue {
  status: AdminAuthStatus;
  token: string | null;
  login: (rawToken: string) => Promise<void>;
  logout: () => void;
}

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null);

export const AdminAuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [token, setToken] = useState<string | null>(() => {
    const saved = sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim();
    return saved ? saved : null;
  });
  const [status, setStatus] = useState<AdminAuthStatus>(() => {
    const saved = sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim();
    return saved ? "checking" : "unauthenticated";
  });

  useEffect(() => {
    let active = true;
    const saved = sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim();
    if (!saved) {
      setToken(null);
      setStatus("unauthenticated");
      return;
    }

    setStatus("checking");
    verifyAdminSession(saved)
      .then(() => {
        if (!active) return;
        setToken(saved);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
        setToken(null);
        setStatus("unauthenticated");
      });

    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (rawToken: string) => {
    const clean = rawToken.trim();
    if (!clean) {
      throw new Error("Please enter an Admin token.");
    }
    await loginAdmin(clean);
    sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, clean);
    setToken(clean);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    setToken(null);
    setStatus("unauthenticated");
  }, []);

  const value = useMemo(
    () => ({ status, token, login, logout }),
    [status, token, login, logout]
  );

  return (
    <AdminAuthContext.Provider value={value}>
      {children}
    </AdminAuthContext.Provider>
  );
};

async function fallbackLogin(rawToken: string): Promise<void> {
  const clean = rawToken.trim();
  await loginAdmin(clean);
  sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, clean);
}

function fallbackLogout(): void {
  sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
}

export function useAdminAuth(): AdminAuthContextValue {
  const ctx = useContext(AdminAuthContext);
  if (ctx) {
    return ctx;
  }

  // Fallback for isolated component tests rendered without AdminAuthProvider
  const stored = sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim() || null;
  return {
    status: stored ? "authenticated" : "unauthenticated",
    token: stored,
    login: fallbackLogin,
    logout: fallbackLogout,
  };
}
