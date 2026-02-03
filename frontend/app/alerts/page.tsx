"use client";

import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";
import DataTable, { Column } from "../../components/DataTable";

type Alert = {
  id: string;
  title: string;
  source: string;
  severity: string;
  service: string;
  timestamp: string;
};

const alerts: Alert[] = [
  {
    id: "AL-2041",
    title: "CPU high on api-prod-3",
    source: "Datadog",
    severity: "warning",
    service: "api-gateway",
    timestamp: "2m ago",
  },
  {
    id: "AL-2038",
    title: "ZeroDivisionError in billing service",
    source: "Sentry",
    severity: "critical",
    service: "billing-svc",
    timestamp: "8m ago",
  },
  {
    id: "AL-2037",
    title: "Cache hit ratio drifting below threshold",
    source: "Datadog",
    severity: "info",
    service: "redis-cache",
    timestamp: "15m ago",
  },
];

const severityColors: Record<string, string> = {
  critical: "text-critical",
  error: "text-critical/80",
  warning: "text-warning",
  info: "text-info",
};

const columns: Column<Alert>[] = [
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
          />
          <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
            Filters
          </button>
        </div>

        <DataTable
          columns={columns}
          data={alerts}
          keyExtractor={(item) => item.id}
          noBorder
        />
      </div>
    </AppShell>
  );
}
