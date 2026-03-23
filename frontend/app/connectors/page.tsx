"use client";

import { useEffect, useState } from "react";
import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";
import { apiFetch } from "../../lib/api";
import { formatDate } from "../../lib/format";
import type {
  Connector as ApiConnector,
  ConnectorListResponse,
  ConnectorPage,
  ConnectorPageListResponse,
} from "../../lib/types";

const SUPPORTED_CONNECTOR_IDS = new Set(["notion", "datadog", "sentry"]);

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
  const [autosavingRoots, setAutosavingRoots] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [notionRoots, setNotionRoots] = useState("");
  const [notionPages, setNotionPages] = useState<ConnectorPage[]>([]);
  const [notionPagesTotal, setNotionPagesTotal] = useState(0);
  const [notionPagesOffset, setNotionPagesOffset] = useState(0);
  const [loadingPages, setLoadingPages] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const notionConnector = connectors.find((item) => item.id === "notion");
  const notionIsSyncing = notionConnector?.last_sync_status === "syncing";
  const configuredNotionRoots = serializeRootPages(notionConnector?.root_pages || []);
  const notionRootsDirty = normalizeRootLines(notionRoots) !== normalizeRootLines(configuredNotionRoots);

  const fetchNotionPages = async (offset = 0, silent = false) => {
    if (!silent) {
      setLoadingPages(true);
    }
    try {
      const data = await apiFetch<ConnectorPageListResponse>(
        `/api/opsrelay/connectors/notion/pages?limit=5&offset=${offset}`,
      );
      setNotionPages(data.items);
      setNotionPagesTotal(data.total);
      setNotionPagesOffset(data.offset);
    } finally {
      if (!silent) {
        setLoadingPages(false);
      }
    }
  };

  const refreshConnectors = async (silentPages = false) => {
    const data = await apiFetch<ConnectorListResponse>("/api/opsrelay/connectors?limit=100");
    const filtered = data.items.filter((item) => SUPPORTED_CONNECTOR_IDS.has(item.id));
    setConnectors(filtered);
    const notion = filtered.find((item) => item.id === "notion");
    if (notion) {
      await fetchNotionPages(notionPagesOffset, silentPages);
    }
    return notion;
  };

  useEffect(() => {
    refreshConnectors().catch(() => setConnectors([]));
  }, []);

  useEffect(() => {
    setNotionRoots(configuredNotionRoots);
  }, [configuredNotionRoots]);

  useEffect(() => {
    if (!notionConnector || notionIsSyncing || !notionRootsDirty) {
      return;
    }

    const trimmedRoots = notionRoots
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);

    if (trimmedRoots.length === 0) {
      return;
    }

    const timeoutId = window.setTimeout(async () => {
      setAutosavingRoots(true);
      try {
        await apiFetch<{ connector: ApiConnector }>("/api/opsrelay/connectors/notion/configure", {
          method: "POST",
          body: { root_pages: trimmedRoots },
        });
        await refreshConnectors(true);
        setMessage(null);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Failed to autosave Notion roots.");
      } finally {
        setAutosavingRoots(false);
      }
    }, 1000);

    return () => window.clearTimeout(timeoutId);
  }, [notionConnector, notionIsSyncing, notionRoots, notionRootsDirty]);

  useEffect(() => {
    if (notionConnector?.last_sync_status !== "syncing") {
      return;
    }

    let active = true;
    const poll = async () => {
      try {
        const notion = await refreshConnectors(true);
        if (!active || !notion) {
          return;
        }
        if (notion.last_sync_status === "succeeded") {
          const syncedCount =
            typeof notion.metadata?.synced_page_count === "number"
              ? notion.metadata.synced_page_count
              : notionPagesTotal;
          setMessage(`Notion sync complete. ${syncedCount} page${syncedCount === 1 ? "" : "s"} synced.`);
        } else if (notion.last_sync_status === "failed") {
          setMessage(notion.last_sync_error || "Notion sync failed.");
        }
      } catch (error) {
        if (active) {
          setMessage(error instanceof Error ? error.message : "Failed to refresh Notion sync status.");
        }
      }
    };

    poll();
    const intervalId = window.setInterval(poll, 2000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [notionConnector?.last_sync_status, notionPagesOffset, notionPagesTotal]);

  const handleConnect = async (id: string) => {
    setMessage(null);
    setConnecting(id);
    try {
      await apiFetch(`/api/opsrelay/connectors/${id}/connect`, { method: "POST" });
      await refreshConnectors();
    } finally {
      setConnecting(null);
    }
  };

  const handleSyncNotion = async () => {
    setMessage(null);
    setSyncing(true);
    try {
      await apiFetch("/api/opsrelay/connectors/notion/sync", { method: "POST" });
      await refreshConnectors();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to sync Notion.");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <AppShell>
      <TopBar title="Connectors" subtitle="Integrations" />

      <div className="border border-mist/10 bg-graphite/30">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
          <h3 className="text-sm font-medium text-white">Integration Sources</h3>
        </div>

        {/* List */}
        <div className="divide-y divide-mist/5">
          {connectors.length === 0 && (
            <div className="px-4 py-6 text-sm text-mist/50">
              No connectors configured.
            </div>
          )}
          {message && (
            <div className="px-4 py-3 text-xs text-accent border-b border-mist/10 bg-slate/20">
              {message}
            </div>
          )}
          {connectors.map((connector) => (
            <div
              key={connector.id}
              className="px-4 py-4 hover:bg-slate/30 transition-colors group"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-white group-hover:text-accent transition-colors">
                      {connector.name}
                    </span>
                    <span className={`inline-block px-2 py-0.5 text-xs ${statusStyles[connector.status] || statusStyles.not_connected}`}>
                      {statusLabels[connector.status] || connector.status}
                    </span>
                    {connector.last_sync_status && (
                      <span className="inline-flex items-center gap-2 px-2 py-0.5 text-xs bg-slate/50 text-mist/60">
                        {connector.last_sync_status === "syncing" && (
                          <span className="h-3 w-3 animate-spin rounded-full border border-mist/25 border-t-accent" />
                        )}
                        {connector.last_sync_status === "syncing" ? "Syncing" : `Sync: ${connector.last_sync_status}`}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-mist/60 mt-1">{connector.detail || "--"}</p>
                  {connector.workspace_name && (
                    <p className="mt-2 text-xs text-mist/45">Workspace: {connector.workspace_name}</p>
                  )}
                  {connector.last_synced_at && (
                    <p className="mt-1 text-xs text-mist/45">Last synced: {formatDate(connector.last_synced_at)}</p>
                  )}
                  {connector.last_sync_error && (
                    <p className="mt-2 text-xs text-warning">Last error: {connector.last_sync_error}</p>
                  )}
                </div>

                {connector.id !== "notion" && connector.status === "not_connected" && (
                  <button
                    className="px-3 py-1.5 text-xs border border-mist/20 text-mist/70 hover:bg-slate/50 hover:text-white transition-colors disabled:opacity-40"
                    onClick={() => handleConnect(connector.id)}
                    disabled={connecting === connector.id}
                  >
                    Connect
                  </button>
                )}
              </div>

              {connector.id === "notion" && (
                <div className="mt-4 border border-mist/10 bg-slate/20 p-4">
                  <label className="block text-[11px] uppercase tracking-wider text-mist/45">
                    <span className="flex items-center gap-2">
                      <span>Root Page URLs or IDs</span>
                      {autosavingRoots && (
                        <span className="inline-flex items-center gap-2 text-[10px] normal-case tracking-normal text-mist/45">
                          <span className="h-3 w-3 animate-spin rounded-full border border-mist/25 border-t-accent" />
                          Saving...
                        </span>
                      )}
                    </span>
                  </label>
                  <textarea
                    className="mt-2 min-h-[120px] w-full border border-mist/15 bg-graphite/50 px-3 py-2 text-sm text-white outline-none placeholder:text-mist/35"
                    placeholder={"One root page per line\nhttps://www.notion.so/... or page ID"}
                    value={notionRoots}
                    onChange={(event) => setNotionRoots(event.target.value)}
                  />
                  <div className="mt-2 text-xs text-mist/45">
                    {(connector.root_pages?.length ?? 0) > 0 ? (
                      <div className="space-y-1">
                        {connector.root_pages?.map((root) => (
                          <p key={root.page_id}>{root.page_url || root.page_id}</p>
                        ))}
                      </div>
                    ) : (
                      <span>No root pages configured.</span>
                    )}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button
                      className="inline-flex items-center gap-2 px-3 py-1.5 text-xs border border-mist/20 text-mist/70 hover:bg-slate/50 hover:text-white transition-colors disabled:opacity-40"
                      onClick={handleSyncNotion}
                      disabled={syncing || notionIsSyncing || autosavingRoots || notionRootsDirty || configuringOrMissing(connector, notionRoots)}
                    >
                      {(syncing || notionIsSyncing) && (
                        <span className="h-3 w-3 animate-spin rounded-full border border-mist/25 border-t-accent" />
                      )}
                      {syncing || notionIsSyncing ? "Syncing" : "Sync Now"}
                    </button>
                  </div>
                  <div className="mt-5 border-t border-mist/10 pt-4">
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] uppercase tracking-wider text-mist/45">
                        Synced Pages ({notionPagesTotal})
                      </p>
                      {loadingPages && (
                        <span className="text-xs text-mist/45">Loading...</span>
                      )}
                    </div>
                    <div className="mt-3 space-y-2">
                      {notionPages.length === 0 && !loadingPages && (
                        <p className="text-xs text-mist/45">No synced Notion pages yet.</p>
                      )}
                      {notionPages.map((page) => (
                        <div key={page.page_id} className="border border-mist/10 bg-graphite/40 px-3 py-2">
                          <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate text-sm text-white">{page.title}</p>
                              <p className="mt-1 text-xs text-mist/45">
                                {page.chunk_count} chunk{page.chunk_count === 1 ? "" : "s"}
                              </p>
                            </div>
                            {page.page_url && (
                              <a
                                href={page.page_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs text-accent hover:underline"
                              >
                                Open
                              </a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 flex items-center justify-between text-xs text-mist/45">
                      <button
                        className="px-2 py-1 border border-mist/15 hover:text-white disabled:opacity-40"
                        disabled={notionPagesOffset === 0 || loadingPages}
                        onClick={() => fetchNotionPages(Math.max(0, notionPagesOffset - 5))}
                      >
                        Previous
                      </button>
                      <span>
                        {notionPagesTotal === 0
                          ? "0-0"
                          : `${notionPagesOffset + 1}-${Math.min(notionPagesOffset + notionPages.length, notionPagesTotal)}`}{" "}
                        of {notionPagesTotal}
                      </span>
                      <button
                        className="px-2 py-1 border border-mist/15 hover:text-white disabled:opacity-40"
                        disabled={loadingPages || notionPagesOffset + notionPages.length >= notionPagesTotal}
                        onClick={() => fetchNotionPages(notionPagesOffset + 5)}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function configuringOrMissing(connector: ApiConnector, notionRoots: string) {
  return (connector.root_pages?.length ?? 0) === 0 && notionRoots.trim().length === 0;
}

function serializeRootPages(roots: ApiConnector["root_pages"] = []) {
  return (roots || []).map((root) => root.page_url || root.page_id).filter(Boolean).join("\n");
}

function normalizeRootLines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}
