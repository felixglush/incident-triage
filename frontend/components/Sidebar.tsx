"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "../lib/api";
import type { DashboardMetricsResponse } from "../lib/types";

const links = [
  { label: "Dashboard", href: "/" },
  { label: "Incidents", href: "/incidents" },
  { label: "Alerts", href: "/alerts" },
  { label: "Runbooks", href: "/runbooks" },
  { label: "Connectors", href: "/connectors" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [metrics, setMetrics] = useState<DashboardMetricsResponse | null>(null);

  useEffect(() => {
    apiFetch<DashboardMetricsResponse>("/api/opsrelay/dashboard/metrics")
      .then((data) => setMetrics(data))
      .catch(() => setMetrics(null));
  }, []);

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <div className="h-full flex flex-col bg-graphite/50 border-r border-mist/10">
      {/* Header */}
      <div className="p-5 border-b border-mist/10">
        <h1 className="font-display text-2xl text-white">Relay</h1>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {links.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.label}
              href={item.href}
              className={`
                block px-3 py-2.5 text-sm transition-colors
                ${active
                  ? "bg-info/15 text-info border-l-2 border-info"
                  : "text-mist/70 hover:bg-slate/50 hover:text-white border-l-2 border-transparent"
                }
              `}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer status */}
      <div className="p-4 pt-5">
        <div className="p-4 bg-slate/30 text-xs text-mist/70">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-success"></span>
            </span>
            <p className="font-mono uppercase tracking-[0.2em]">Live</p>
          </div>
          <p className="mt-3">{metrics?.active_incidents ?? 0} active incidents</p>
          <p>MTTR {metrics?.mttr_minutes !== null && metrics?.mttr_minutes !== undefined ? `${metrics.mttr_minutes}m` : "--"}</p>
        </div>
      </div>
    </div>
  );
}
