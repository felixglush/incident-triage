"use client";

import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";
import DataTable, { Column } from "../../components/DataTable";

type Incident = {
  id: string;
  title: string;
  status: string;
  statusType: string;
  severity: string;
  severityType: string;
  service: string;
  updated: string;
};

const incidents: Incident[] = [
  {
    id: "INC-1042",
    title: "Database connection pool exhausted",
    status: "Investigating",
    statusType: "investigating",
    severity: "Critical",
    severityType: "critical",
    service: "platform-db",
    updated: "2m ago",
  },
  {
    id: "INC-1041",
    title: "API latency spike in us-east-1",
    status: "Open",
    statusType: "open",
    severity: "Warning",
    severityType: "warning",
    service: "api-gateway",
    updated: "14m ago",
  },
  {
    id: "INC-1038",
    title: "Billing webhook failure",
    status: "Resolved",
    statusType: "resolved",
    severity: "Error",
    severityType: "error",
    service: "billing-svc",
    updated: "1h ago",
  },
];

const severityColors: Record<string, string> = {
  critical: "text-critical",
  error: "text-critical/80",
  warning: "text-warning",
  info: "text-info",
};

const statusColors: Record<string, string> = {
  investigating: "bg-warning/20 text-warning",
  open: "bg-info/20 text-info",
  resolved: "bg-success/20 text-success",
};

const columns: Column<Incident>[] = [
  {
    key: "id",
    header: "ID",
    width: "90px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/50">{item.id}</span>
    ),
  },
  {
    key: "title",
    header: "Incident",
    render: (item) => (
      <span className="text-sm text-white group-hover:text-accent transition-colors truncate block">
        {item.title}
      </span>
    ),
  },
  {
    key: "service",
    header: "Service",
    width: "120px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/60">{item.service}</span>
    ),
  },
  {
    key: "status",
    header: "Status",
    width: "110px",
    render: (item) => (
      <span className={`inline-block px-2 py-0.5 text-xs ${statusColors[item.statusType]}`}>
        {item.status}
      </span>
    ),
  },
  {
    key: "severity",
    header: "Severity",
    width: "80px",
    render: (item) => (
      <span className={`text-xs font-medium ${severityColors[item.severityType]}`}>
        {item.severity}
      </span>
    ),
  },
  {
    key: "updated",
    header: "Updated",
    width: "80px",
    align: "right",
    render: (item) => (
      <span className="text-xs text-mist/50">{item.updated}</span>
    ),
  },
];

export default function Page() {
  return (
    <AppShell>
      <TopBar title="Incidents" subtitle="Overview" />

      <div className="border border-mist/10 bg-graphite/30">
        {/* Search bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-mist/10">
          <svg className="w-4 h-4 text-mist/40" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            className="flex-1 bg-transparent text-sm text-mist placeholder:text-mist/40 focus:outline-none"
            placeholder="Search incidents by title, service, or ID..."
          />
          <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
            Filters
          </button>
        </div>

        <DataTable
          columns={columns}
          data={incidents}
          keyExtractor={(item) => item.id}
          href={(item) => `/incidents/${item.id}`}
          noBorder
        />
      </div>
    </AppShell>
  );
}
