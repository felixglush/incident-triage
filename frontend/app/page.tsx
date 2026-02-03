"use client";

import AppShell from "../components/AppShell";
import TopBar from "../components/TopBar";
import DataTable, { Column } from "../components/DataTable";
import IncidentHeatmap from "../components/IncidentHeatmap";

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
      <TopBar title="Overview" subtitle="Dashboard" />

      {/* Metrics bar */}
      <div className="border border-mist/10 bg-graphite/30">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 divide-x divide-mist/10">
          {/* Active Incidents */}
          <div className="px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-display text-white">2</span>
              <span className="text-xs text-mist/50">active</span>
            </div>
            <p className="text-xs text-mist/40 mt-0.5">Incidents</p>
          </div>

          {/* Critical */}
          <div className="px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-display text-critical">1</span>
              <span className="text-xs text-critical/60">critical</span>
            </div>
            <p className="text-xs text-mist/40 mt-0.5">Needs attention</p>
          </div>

          {/* Open Alerts */}
          <div className="px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-display text-white">7</span>
              <span className="text-xs text-mist/50">untriaged</span>
            </div>
            <p className="text-xs text-mist/40 mt-0.5">Alerts</p>
          </div>

          {/* MTTA */}
          <div className="px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-display text-white">3m</span>
              <span className="text-xs text-success">↓ 12%</span>
            </div>
            <p className="text-xs text-mist/40 mt-0.5">MTTA (7d avg)</p>
          </div>

          {/* MTTR */}
          <div className="px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-display text-white">42m</span>
              <span className="text-xs text-warning">↑ 8%</span>
            </div>
            <p className="text-xs text-mist/40 mt-0.5">MTTR (7d avg)</p>
          </div>

        </div>
      </div>

      {/* Incident Heatmap */}
      <IncidentHeatmap />

      {/* Table with header */}
      <div className="border border-mist/10 bg-graphite/30">
        <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
          <h3 className="text-sm font-medium text-white">Live Incident Queue</h3>
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
