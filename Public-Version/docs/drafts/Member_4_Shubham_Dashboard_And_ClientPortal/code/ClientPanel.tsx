import React from "react";
import { Laptop } from "lucide-react";
import type { ClientStats } from "../lib/types";

interface ClientPanelProps {
  clients: ClientStats[];
}

export const ClientPanel: React.FC<ClientPanelProps> = ({ clients }) => {
  return (
    <div className="rounded-xl bg-slate-900/90 border border-slate-800 p-4 shadow-lg flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">
            Connected Client Laptops (Superposed Poisson Streams)
          </h2>
          <p className="text-xs text-slate-400">
            Per-client arrival rate (&lambda;_i), queue wait, and internal worker VM distribution
          </p>
        </div>
        <span className="text-xs font-mono text-cyan-300">
          {clients.length} Active Client(s)
        </span>
      </div>

      {clients.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-400 border border-dashed border-slate-800 rounded-lg">
          No client laptops have sent tasks yet. Run{" "}
          <code className="text-cyan-300">cb-traffic</code> or open{" "}
          <code className="text-cyan-300">/client</code>.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {clients.map((client) => {
            const workerEntries = Object.entries(client.served_by).sort(([a], [b]) =>
              a.localeCompare(b)
            );
            const totalServed = workerEntries.reduce((acc, [, cnt]) => acc + cnt, 0);

            return (
              <div
                key={client.client_id}
                data-testid={`client-card-${client.client_id}`}
                className="rounded-lg bg-slate-950/80 border border-slate-800 p-3.5 space-y-2.5"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Laptop className="w-4 h-4 text-cyan-400" />
                    <span className="text-xs font-bold font-mono text-white">
                      {client.client_id}
                    </span>
                  </div>
                  <span className="text-xs font-mono font-semibold text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">
                    {client.req_per_sec.toFixed(1)} req/s
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-2 text-[11px] font-mono text-slate-400 bg-slate-900/70 p-2 rounded">
                  <div>
                    <div className="text-[10px] text-slate-500">Total Sent</div>
                    <div className="text-white font-semibold">{client.total_sent}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500">Queued</div>
                    <div className="text-amber-300 font-semibold">{client.queued}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500">Queue Wait</div>
                    <div className="text-cyan-300 font-semibold">
                      {client.avg_queue_wait_ms.toFixed(1)}ms
                    </div>
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="text-[10px] font-mono uppercase text-slate-400">
                    Served By Worker VMs ({totalServed} tasks)
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {workerEntries.map(([wid, count]) => (
                      <span
                        key={wid}
                        className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-200 border border-slate-700"
                      >
                        {wid}: <strong className="text-cyan-300">{count}</strong>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

