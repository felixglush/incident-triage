"use client";

import { useEffect, useMemo, useState } from "react";
import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";
import DataTable, { Column } from "../../components/DataTable";
import { apiFetch } from "../../lib/api";
import { formatTime } from "../../lib/format";
import type { Alert as ApiAlert, AlertListResponse } from "../../lib/types";

type AlertRow = {
  id: string;
  title: string;
  source: string;
  severity: string;
  service: string;
  timestamp: string;
};

const severityColors: Record<string, string> = {
  critical: "text-critical",
  error: "text-critical/80",
  warning: "text-warning",
  info: "text-info",
};

const columns: Column<AlertRow>[] = [
  {
    key: "id",
    header: "ID",
    width: "80px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/50">{item.id}</span>
    ),
  },
  {
    key: "title",
    header: "Alert",
    render: (item) => (
      <span className="text-sm text-white group-hover:text-accent transition-colors truncate block">
        {item.title}
      </span>
    ),
  },
  {
    key: "service",
    header: "Service",
    width: "110px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/60">{item.service}</span>
    ),
  },
  {
    key: "source",
    header: "Source",
    width: "90px",
    render: (item) => (
      <span className="text-xs text-mist/60">{item.source}</span>
    ),
  },
  {
    key: "severity",
    header: "Severity",
    width: "80px",
    render: (item) => (
      <span className={`text-xs font-medium uppercase ${severityColors[item.severity]}`}>
        {item.severity}
      </span>
    ),
  },
  {
    key: "timestamp",
    header: "Time",
    width: "70px",
    align: "right",
    render: (item) => (
      <span className="text-xs text-mist/50">{item.timestamp}</span>
    ),
  },
];

export default function Page() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<AlertRow[]>([]);

  useEffect(() => {
    apiFetch<AlertListResponse>("/api/opsrelay/alerts?limit=50")
      .then((data) => {
        const mapped = data.items.map((alert: ApiAlert) => ({
          id: `AL-${alert.id}`,
          title: alert.title,
          source: alert.source,
          severity: (alert.severity || "info").toLowerCase(),
          service: alert.service_name || "unknown",
          timestamp: formatTime(alert.alert_timestamp),
        }));
        setRows(mapped);
      })
      .catch(() => setRows([]));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) => {
      const hay = `${row.id} ${row.title} ${row.source} ${row.service}`.toLowerCase();
      return hay.includes(q);
    });
  }, [rows, query]);

  return (
    <AppShell>
      <TopBar title="Alerts Inbox" subtitle="Incoming" />

      <div className="border border-mist/10 bg-graphite/30">
        {/* Search bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-mist/10">
          <svg className="w-4 h-4 text-mist/40" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            className="flex-1 bg-transparent text-sm text-mist placeholder:text-mist/40 focus:outline-none"
            placeholder="Search alerts by message, source, or service..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
            Filters
          </button>
        </div>

        <DataTable
          columns={columns}
          data={filtered}
          keyExtractor={(item) => item.id}
          noBorder
          emptyMessage="No alerts found."
        />
      </div>
    </AppShell>
  );
}
