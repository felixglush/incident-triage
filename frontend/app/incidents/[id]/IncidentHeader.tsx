import { formatDateTime } from "../../../lib/format";

type IncidentHeaderProps = {
  incidentId: string;
  title: string;
  severity: string;
  status: string;
  service?: string | null;
  updatedAt?: string | null;
  onAdvanceStatus?: () => void;
  nextStatusLabel?: string | null;
  statusUpdating?: boolean;
};

const severityColors: Record<string, string> = {
  critical: "text-critical",
  error: "text-critical/80",
  warning: "text-warning",
  info: "text-info",
};

const statusColors: Record<string, string> = {
  open: "bg-info/20 text-info",
  investigating: "bg-warning/20 text-warning",
  resolved: "bg-success/20 text-success",
  closed: "bg-mist/20 text-mist/60",
};

export default function IncidentHeader({
  incidentId,
  title,
  severity,
  status,
  service,
  updatedAt,
  onAdvanceStatus,
  nextStatusLabel,
  statusUpdating = false,
}: IncidentHeaderProps) {
  const updatedLabel = formatDateTime(updatedAt);
  const statusKey = status?.toLowerCase() || "open";
  const severityKey = severity?.toLowerCase() || "info";

  return (
    <header className="border border-mist/10 bg-graphite/30">
      <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-4">
        <div>
          <div className="flex items-center gap-3 text-xs">
            <span className="font-mono text-mist/50">INC-{incidentId}</span>
            <span className={severityColors[severityKey] || "text-mist/60"}>
              {severity}
            </span>
            <span className={`px-2 py-0.5 ${statusColors[statusKey] || "bg-mist/20 text-mist/60"}`}>
              {status}
            </span>
            {service && <span className="text-mist/50">{service}</span>}
            <span className="text-mist/40">{updatedLabel}</span>
          </div>
          <h2 className="text-xl text-white mt-2">
            {title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="border border-mist/20 px-4 py-2 text-xs text-mist/70 hover:bg-slate/50 hover:text-white transition-colors disabled:opacity-40"
            onClick={onAdvanceStatus}
            disabled={!onAdvanceStatus || !nextStatusLabel || statusUpdating}
          >
            {nextStatusLabel ? `Advance to ${nextStatusLabel}` : "Update Status"}
          </button>
        </div>
      </div>
    </header>
  );
}
