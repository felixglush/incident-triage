"use client";

import { useEffect, useMemo, useState } from "react";
import AppShell from "../../components/AppShell";
import TopBar from "../../components/TopBar";
import DataTable, { Column } from "../../components/DataTable";
import { apiFetch } from "../../lib/api";
import { formatDate } from "../../lib/format";
import type { Runbook as ApiRunbook, RunbookListResponse } from "../../lib/types";

type RunbookRow = {
  id: string;
  title: string;
  source: string;
  tags: string[];
  lastUpdated: string;
};

const columns: Column<RunbookRow>[] = [
  {
    key: "id",
    header: "ID",
    width: "70px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/50">{item.id}</span>
    ),
  },
  {
    key: "title",
    header: "Runbook",
    render: (item) => (
      <span className="text-sm text-white group-hover:text-accent transition-colors">
        {item.title}
      </span>
    ),
  },
  {
    key: "source",
    header: "Source",
    width: "160px",
    render: (item) => (
      <span className="text-xs font-mono text-mist/60">{item.source}</span>
    ),
  },
  {
    key: "tags",
    header: "Tags",
    width: "150px",
    render: (item) => (
      <div className="flex gap-1.5 flex-wrap">
        {item.tags.map((tag) => (
          <span
            key={tag}
            className="bg-slate/60 px-2 py-0.5 text-xs text-mist/60"
          >
            {tag}
          </span>
        ))}
      </div>
    ),
  },
  {
    key: "lastUpdated",
    header: "Updated",
    width: "80px",
    align: "right",
    render: (item) => (
      <span className="text-xs text-mist/50">{item.lastUpdated}</span>
    ),
  },
];

export default function Page() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<RunbookRow[]>([]);

  useEffect(() => {
    apiFetch<RunbookListResponse>("/api/opsrelay/runbooks?limit=100")
      .then((data) => {
        const mapped = data.items.map((runbook: ApiRunbook) => ({
          id: runbook.id,
          title: runbook.title,
          source: runbook.source,
          tags: runbook.tags || [],
          lastUpdated: formatDate(runbook.last_updated),
        }));
        setRows(mapped);
      })
      .catch(() => setRows([]));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) => {
      const hay = `${row.id} ${row.title} ${row.tags.join(" ")} ${row.source}`.toLowerCase();
      return hay.includes(q);
    });
  }, [rows, query]);

  return (
    <AppShell>
      <TopBar title="Runbook Explorer" subtitle="Knowledge" />

      <div className="border border-mist/10 bg-graphite/30">
        {/* Search bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-mist/10">
          <svg className="w-4 h-4 text-mist/40" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            className="flex-1 bg-transparent text-sm text-mist placeholder:text-mist/40 focus:outline-none"
            placeholder="Search runbooks by title or tag..."
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
          href={(item) => `/runbooks/${item.id}`}
          noBorder
          emptyMessage="No runbooks available."
        />
      </div>
    </AppShell>
  );
}
