"use client";

import { useEffect, useState } from "react";
import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";
import { apiFetch } from "../../lib/api";
import type { Connector as ApiConnector, ConnectorListResponse } from "../../lib/types";

const statusStyles: Record<string, string> = {
  connected: "bg-success/20 text-success",
  not_connected: "bg-slate/40 text-mist/50",
};

const statusLabels: Record<string, string> = {
  connected: "Connected",
  not_connected: "Not Connected",
};

export default function Page() {
  const [connectors, setConnectors] = useState<ApiConnector[]>([]);
  const [connecting, setConnecting] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ConnectorListResponse>("/api/opsrelay/connectors?limit=100")
      .then((data) => setConnectors(data.items))
      .catch(() => setConnectors([]));
  }, []);

  const handleConnect = async (id: string) => {
    setConnecting(id);
    try {
      await apiFetch(`/api/opsrelay/connectors/${id}/connect`, { method: "POST" });
      const refreshed = await apiFetch<ConnectorListResponse>("/api/opsrelay/connectors?limit=100");
      setConnectors(refreshed.items);
    } finally {
      setConnecting(null);
    }
  };

  return (
    <AppShell>
      <TopBar title="Connectors" subtitle="Integrations" />

      <div className="border border-mist/10 bg-graphite/30">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
          <h3 className="text-sm font-medium text-white">Integration Sources</h3>
          <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
            Add Connector
          </button>
        </div>

        {/* List */}
        <div className="divide-y divide-mist/5">
          {connectors.length === 0 && (
            <div className="px-4 py-6 text-sm text-mist/50">
              No connectors configured.
            </div>
          )}
          {connectors.map((connector) => (
            <div
              key={connector.id}
              className="flex items-center justify-between px-4 py-4 hover:bg-slate/30 transition-colors group cursor-pointer"
            >
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-white group-hover:text-accent transition-colors">
                    {connector.name}
                  </span>
                  <span className={`inline-block px-2 py-0.5 text-xs ${statusStyles[connector.status] || statusStyles.inactive}`}>
                    {statusLabels[connector.status] || connector.status}
                  </span>
                </div>
                <p className="text-xs text-mist/60 mt-1">{connector.detail || "--"}</p>
              </div>
              
              {connector.status === "connected" && (
                <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
                  Configure
                </button>
              )}
              {connector.status === "not_connected" && (
                <button
                  className="px-3 py-1.5 text-xs border border-mist/20 text-mist/70 hover:bg-slate/50 hover:text-white transition-colors disabled:opacity-40"
                  onClick={() => handleConnect(connector.id)}
                  disabled={connecting === connector.id}
                >
                  Connect
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
