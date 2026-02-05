"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import AppShell from "../../../components/AppShell";
import ChatPanel from "../../../components/ChatPanel";
import IncidentHeader from "./IncidentHeader";
import { apiFetch } from "../../../lib/api";
import { formatDateTime, formatTime } from "../../../lib/format";
import type {
  IncidentDetailResponse,
  SimilarIncidentResponse,
  RunbookSearchItem,
  RunbookSearchResponse,
} from "../../../lib/types";

const statusNext: Record<string, string | null> = {
  open: "investigating",
  investigating: "resolved",
  resolved: "closed",
  closed: null,
};

export default function Page() {
  const params = useParams();
  const incidentId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const [detail, setDetail] = useState<IncidentDetailResponse | null>(null);
  const [similar, setSimilar] = useState<SimilarIncidentResponse | null>(null);
  const [runbooks, setRunbooks] = useState<RunbookSearchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusUpdating, setStatusUpdating] = useState(false);

  useEffect(() => {
    if (!incidentId) return;
    let isMounted = true;
    setLoading(true);
    Promise.all([
      apiFetch<IncidentDetailResponse>(`/api/opsrelay/incidents/${incidentId}`),
      apiFetch<SimilarIncidentResponse>(`/api/opsrelay/incidents/${incidentId}/similar?limit=5`),
    ])
      .then(async ([detailRes, similarRes]) => {
        if (!isMounted) return;
        setDetail(detailRes);
        setSimilar(similarRes);
        const queryParts = [
          detailRes.incident.title,
          detailRes.incident.summary,
          (detailRes.incident.affected_services || []).join(" "),
        ].filter(Boolean);
        const query = queryParts.join(" ").trim();
        if (!query) {
          setRunbooks([]);
          return;
        }
        const runbookRes = await apiFetch<RunbookSearchResponse>(
          `/api/opsrelay/runbooks/search?q=${encodeURIComponent(query)}&limit=5`,
        );
        if (!isMounted) return;
        setRunbooks(runbookRes.items || []);
      })
      .catch(() => {
        if (!isMounted) return;
        setDetail(null);
        setSimilar(null);
        setRunbooks([]);
      })
      .finally(() => {
        if (!isMounted) return;
        setLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [incidentId]);

  const timeline = useMemo(() => {
    if (!detail) return [];
    const alerts = detail.alerts.map((alert) => ({
      time: alert.alert_timestamp || alert.created_at || "",
      title: alert.title,
      detail: alert.message || `${alert.source} alert`,
    }));
    const actions = detail.actions.map((action) => ({
      time: action.timestamp || "",
      title: action.action_type,
      detail: action.description,
    }));
    return [...actions, ...alerts].sort((a, b) => (b.time || "").localeCompare(a.time || ""));
  }, [detail]);

  const nextSteps = detail?.incident.next_steps || [];

  const chatReferences = useMemo(() => {
    const refs = (similar?.items || []).map((item) => ({
      label: `INC-${item.id}`,
      href: `/incidents/${item.id}`,
    }));
    runbooks.forEach((item) => {
      refs.push({
        label: item.title || item.source_document,
        href: "/runbooks",
      });
    });
    return refs;
  }, [similar, runbooks]);

  const handleAdvanceStatus = async () => {
    if (!detail || !incidentId) return;
    const current = detail.incident.status?.toLowerCase() || "open";
    const next = statusNext[current];
    if (!next) return;
    setStatusUpdating(true);
    try {
      await apiFetch(`/api/opsrelay/incidents/${incidentId}/status?status=${next}`, {
        method: "PATCH",
      });
      const refreshed = await apiFetch<IncidentDetailResponse>(
        `/api/opsrelay/incidents/${incidentId}`,
      );
      setDetail(refreshed);
    } finally {
      setStatusUpdating(false);
    }
  };

  if (!incidentId) {
    return (
      <AppShell>
        <div className="text-mist/60">Missing incident id.</div>
      </AppShell>
    );
  }

  return (
    <AppShell rightPanel={<ChatPanel references={chatReferences} incidentId={incidentId} endpoint={undefined} />}>
      <IncidentHeader
        incidentId={incidentId}
        title={detail?.incident.title || "Loading incident"}
        severity={detail?.incident.severity || "--"}
        status={detail?.incident.status || "open"}
        service={detail?.incident.affected_services?.[0] || null}
        updatedAt={detail?.incident.updated_at || null}
        onAdvanceStatus={handleAdvanceStatus}
        nextStatusLabel={detail ? statusNext[detail.incident.status?.toLowerCase() || "open"] : null}
        statusUpdating={statusUpdating}
      />

      {/* Two-column layout for main content */}
      <div className="grid gap-6 xl:grid-cols-2">
        {/* Left column - Timeline */}
        <div className="border border-mist/10 bg-graphite/30">
          <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
            <h3 className="text-sm font-medium text-white">Incident Feed</h3>
            <span className="text-xs text-mist/50">
              {detail?.incident.updated_at ? `Updated ${formatDateTime(detail.incident.updated_at)}` : "Updated --"}
            </span>
          </div>
          <div className="divide-y divide-mist/5">
            {timeline.length === 0 && (
              <div className="px-4 py-4 text-sm text-mist/50">
                {loading ? "Loading incident activity..." : "No activity recorded yet."}
              </div>
            )}
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
                    <span className="font-mono text-xs text-mist/50">
                      {formatTime(item.time)}
                    </span>
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
              {(similar?.items || []).length === 0 && (
                <div className="px-4 py-4 text-sm text-mist/50">
                  {loading ? "Finding similar incidents..." : "No similar incidents yet."}
                </div>
              )}
              {(similar?.items || []).map((item) => (
                <a
                  key={item.id}
                  href={`/incidents/${item.id}`}
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate/30 transition-colors group"
                >
                  <div className="min-w-0">
                    <span className="text-xs font-mono text-mist/50">INC-{item.id}</span>
                    <p className="text-sm text-white group-hover:text-accent transition-colors truncate">
                      {item.title}
                    </p>
                  </div>
                  <span className="text-xs text-info flex-shrink-0">{item.score.toFixed(2)}</span>
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
              {runbooks.length === 0 && (
                <div className="px-4 py-4 text-sm text-mist/50">
                  {loading ? "Loading runbooks..." : "No runbook references available."}
                </div>
              )}
              {runbooks.map((item) => (
                <a
                  key={item.id}
                  href="/runbooks"
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-slate/30 transition-colors group"
                >
                  <div className="min-w-0">
                    <p className="text-sm text-white group-hover:text-accent transition-colors">
                      {item.title || item.source_document}
                    </p>
                    <span className="text-xs font-mono text-mist/50">{item.source_document}</span>
                  </div>
                  <span className="text-xs text-info flex-shrink-0">
                    {item.score.toFixed(2)}
                  </span>
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
          {nextSteps.length === 0 && (
            <div className="px-4 py-4 text-sm text-mist/50">
              {loading ? "Loading next steps..." : "No next steps available."}
            </div>
          )}
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
