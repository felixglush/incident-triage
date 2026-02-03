import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";

const connectors = [
  { id: "notion", name: "Notion", status: "Not Connected", detail: "Runbook sync", statusType: "inactive" },
  { id: "slack", name: "Slack", status: "Pending", detail: "Incident channel history", statusType: "pending" },
  { id: "linear", name: "Linear", status: "Connected", detail: "Issue context", statusType: "active" },
  { id: "datadog", name: "Datadog", status: "Connected", detail: "Metrics and alerts", statusType: "active" },
  { id: "sentry", name: "Sentry", status: "Connected", detail: "Error tracking", statusType: "active" },
  { id: "pagerduty", name: "PagerDuty", status: "Not Connected", detail: "On-call scheduling", statusType: "inactive" },
];

const statusStyles: Record<string, string> = {
  active: "bg-success/20 text-success",
  pending: "bg-warning/20 text-warning",
  inactive: "bg-slate/40 text-mist/50",
};

export default function Page() {
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
                  <span className={`inline-block px-2 py-0.5 text-xs ${statusStyles[connector.statusType]}`}>
                    {connector.status}
                  </span>
                </div>
                <p className="text-xs text-mist/60 mt-1">{connector.detail}</p>
              </div>
              
              {connector.statusType === "active" && (
                <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
                  Configure
                </button>
              )}
              {connector.statusType === "inactive" && (
                <button className="px-3 py-1.5 text-xs border border-mist/20 text-mist/70 hover:bg-slate/50 hover:text-white transition-colors">
                  Connect
                </button>
              )}
              {connector.statusType === "pending" && (
                <button className="px-3 py-1.5 text-xs text-mist/60 hover:text-white transition-colors">
                  View
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
