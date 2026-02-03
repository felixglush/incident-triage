import AppShell from "../../../components/AppShell";
import ChatPanel from "../../../components/ChatPanel";
import IncidentHeader from "./IncidentHeader";

const timeline = [
  { time: "14:02", title: "Alert grouped", detail: "Datadog alert added to incident" },
  { time: "14:05", title: "Service degradation", detail: "Connection pool reached 95%" },
  { time: "14:08", title: "Action taken", detail: "Restarted primary DB replicas" },
];

const similar = [
  { id: "INC-0921", title: "DB connection spikes during deploy", score: "0.86" },
  { id: "INC-0897", title: "Pool saturation on worker fleet", score: "0.74" },
];

const runbooks = [
  { id: "RB-001", title: "Postgres Connection Pool", source: "db-troubleshooting.md" },
  { id: "RB-002", title: "Rate-limiting DB clients", source: "capacity.md" },
];

const nextSteps = [
  "Page on-call and open incident bridge",
  "Verify connection limits in production",
  "Check for long-running queries in pg_stat_activity",
];

export default function Page() {
  const chatReferences = [
    { label: "INC-0921", href: "/incidents/INC-0921" },
    { label: "INC-0897", href: "/incidents/INC-0897" },
    { label: "Runbook: Pooling", href: "/runbooks" },
  ];

  return (
    <AppShell rightPanel={<ChatPanel references={chatReferences} />}>
      <IncidentHeader />

      {/* Two-column layout for main content */}
      <div className="grid gap-6 xl:grid-cols-2">
        {/* Left column - Timeline */}
        <div className="border border-mist/10 bg-graphite/30">
          <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
            <h3 className="text-sm font-medium text-white">Incident Feed</h3>
            <span className="text-xs text-mist/50">Updated 2m ago</span>
          </div>
          <div className="divide-y divide-mist/5">
            {timeline.map((item, i) => (
              <div key={item.time} className="flex items-start gap-3 px-4 py-3 hover:bg-slate/30 transition-colors">
                <div
                  className={`mt-1 h-2 w-2 flex-shrink-0 rounded-full ${
                    i === 0 ? "bg-info" : "bg-mist/30"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm text-white">{item.title}</p>
                    <span className="font-mono text-xs text-mist/50">{item.time}</span>
                  </div>
                  <p className="text-xs text-mist/60 mt-0.5">{item.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right column - Similar & Runbooks */}
        <div className="space-y-6">
          {/* Similar Incidents */}
          <div className="border border-mist/10 bg-graphite/30">
            <div className="px-4 py-3 border-b border-mist/10">
              <h3 className="text-sm font-medium text-white">Similar Incidents</h3>
            </div>
            <div className="divide-y divide-mist/5">
              {similar.map((item) => (
                <a
                  key={item.id}
                  href={`/incidents/${item.id}`}
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate/30 transition-colors group"
                >
                  <div className="min-w-0">
                    <span className="text-xs font-mono text-mist/50">{item.id}</span>
                    <p className="text-sm text-white group-hover:text-accent transition-colors truncate">
                      {item.title}
                    </p>
                  </div>
                  <span className="text-xs text-info flex-shrink-0">{item.score}</span>
                </a>
              ))}
            </div>
          </div>

          {/* Runbook References */}
          <div className="border border-mist/10 bg-graphite/30">
            <div className="px-4 py-3 border-b border-mist/10">
              <h3 className="text-sm font-medium text-white">Runbook References</h3>
            </div>
            <div className="divide-y divide-mist/5">
              {runbooks.map((item) => (
                <a
                  key={item.id}
                  href="/runbooks"
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate/30 transition-colors group"
                >
                  <div className="min-w-0">
                    <p className="text-sm text-white group-hover:text-accent transition-colors">
                      {item.title}
                    </p>
                    <span className="text-xs font-mono text-mist/50">{item.source}</span>
                  </div>
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Next Steps - full width */}
      <div className="border border-mist/10 bg-graphite/30">
        <div className="px-4 py-3 border-b border-mist/10">
          <h3 className="text-sm font-medium text-white">Suggested Next Steps</h3>
        </div>
        <div className="divide-y divide-mist/5">
          {nextSteps.map((step, i) => (
            <div
              key={step}
              className="flex items-center gap-3 px-4 py-3 hover:bg-slate/30 transition-colors"
            >
              <span className="flex h-5 w-5 items-center justify-center bg-slate/50 text-xs text-mist/60 flex-shrink-0">
                {i + 1}
              </span>
              <span className="text-sm text-mist/80">{step}</span>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
