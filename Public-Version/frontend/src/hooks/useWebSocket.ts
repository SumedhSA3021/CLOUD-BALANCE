/** WebSocket hook with exponential backoff reconnect, stale-data detection, and 60-point rolling history. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchSnapshotFallback } from "../lib/api";
import type { ClusterSnapshot, WorkerHistoryPoint } from "../lib/types";

export type ConnectionState = "CONNECTING" | "CONNECTED" | "RECONNECTING" | "DISCONNECTED";

const MAX_HISTORY_POINTS = 60;
const STALE_THRESHOLD_MS = 4500;

function resolveWsUrl(token: string): string {
  let base: string;
  const custom = import.meta.env.VITE_WS_URL;
  if (custom) {
    base = custom;
  } else {
    const apiBase = import.meta.env.VITE_API_BASE_URL;
    if (apiBase && /^https?:\/\//i.test(apiBase)) {
      base = apiBase.replace(/^http/i, "ws").replace(/\/$/, "") + "/ws";
    } else {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      base = `${proto}//${window.location.host}/ws`;
    }
  }
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}token=${encodeURIComponent(token)}`;
}

export interface UseClusterWebSocketResult {
  snapshot: ClusterSnapshot | null;
  history: WorkerHistoryPoint[];
  connectionState: ConnectionState;
  isStale: boolean;
  error: string | null;
  refreshNow: () => Promise<void>;
}

export function useWebSocket(
  token: string | null = null,
  onUnauthorized?: () => void
): UseClusterWebSocketResult {
  const [snapshot, setSnapshot] = useState<ClusterSnapshot | null>(null);
  const [history, setHistory] = useState<WorkerHistoryPoint[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    token ? "CONNECTING" : "DISCONNECTED"
  );
  const [isStale, setIsStale] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const lastMessageAtRef = useRef<number>(Date.now());
  const retryCountRef = useRef<number>(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const mountedRef = useRef<boolean>(true);
  const onUnauthorizedRef = useRef<(() => void) | undefined>(onUnauthorized);
  onUnauthorizedRef.current = onUnauthorized;

  const applySnapshot = useCallback((incoming: ClusterSnapshot) => {
    lastMessageAtRef.current = Date.now();
    setIsStale(false);
    setError(null);
    setSnapshot(incoming);

    const timeLabel = new Date(incoming.timestamp).toLocaleTimeString([], {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

    const cpuByWorker: Record<string, number> = {};
    const memByWorker: Record<string, number> = {};
    for (const w of incoming.workers) {
      cpuByWorker[w.worker_id] = w.cpu_percent;
      memByWorker[w.worker_id] = w.memory_percent;
    }

    setHistory((prev) => {
      const next = [...prev, { timestampLabel: timeLabel, cpuByWorker, memByWorker }];
      return next.length > MAX_HISTORY_POINTS
        ? next.slice(next.length - MAX_HISTORY_POINTS)
        : next;
    });
  }, []);

  const refreshNow = useCallback(async () => {
    if (!token) return;
    try {
      const snap = await fetchSnapshotFallback(token);
      if (mountedRef.current) {
        applySnapshot(snap);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorizedRef.current?.();
        return;
      }
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : "Failed to fetch cluster snapshot");
      }
    }
  }, [token, applySnapshot]);

  useEffect(() => {
    mountedRef.current = true;
    if (!token) {
      setConnectionState("DISCONNECTED");
      return () => {
        mountedRef.current = false;
      };
    }

    const connectWs = () => {
      if (!mountedRef.current) return;

      try {
        const ws = new WebSocket(resolveWsUrl(token));
        wsRef.current = ws;

        ws.onopen = () => {
          if (!mountedRef.current) return;
          retryCountRef.current = 0;
          setConnectionState("CONNECTED");
          setError(null);
        };

        ws.onmessage = (event: MessageEvent) => {
          if (!mountedRef.current) return;
          try {
            const parsed = JSON.parse(String(event.data));
            if (parsed?.type === "CLUSTER_SNAPSHOT") {
              applySnapshot(parsed as ClusterSnapshot);
            }
          } catch {
            // ignore malformed frame
          }
        };

        ws.onerror = () => {
          if (!mountedRef.current) return;
          setError("WebSocket stream interrupted; attempting automatic recovery");
        };

        ws.onclose = (event: CloseEvent) => {
          if (!mountedRef.current) return;
          if (event.code === 1008) {
            setConnectionState("DISCONNECTED");
            onUnauthorizedRef.current?.();
            return;
          }
          setConnectionState("RECONNECTING");
          const attempt = retryCountRef.current;
          retryCountRef.current += 1;
          const backoffMs = Math.min(8000, 500 * Math.pow(2, attempt));
          reconnectTimerRef.current = window.setTimeout(connectWs, backoffMs);
        };
      } catch {
        setConnectionState("DISCONNECTED");
      }
    };

    connectWs();
    void refreshNow();

    const staleTimer = window.setInterval(() => {
      if (!mountedRef.current) return;
      const elapsed = Date.now() - lastMessageAtRef.current;
      if (elapsed > STALE_THRESHOLD_MS) {
        setIsStale(true);
        void refreshNow();
      }
    }, 2000);

    return () => {
      mountedRef.current = false;
      window.clearInterval(staleTimer);
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [token, applySnapshot, refreshNow]);

  return {
    snapshot,
    history,
    connectionState,
    isStale,
    error,
    refreshNow,
  };
}

