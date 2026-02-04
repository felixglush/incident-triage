"use client";

import { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: string;
  width?: string;
  align?: "left" | "right" | "center";
  render: (item: T) => ReactNode;
};

type DataTableProps<T> = {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (item: T) => string;
  onRowClick?: (item: T) => void;
  href?: (item: T) => string;
  noBorder?: boolean;
  emptyMessage?: string;
};

export default function DataTable<T>({
  columns,
  data,
  keyExtractor,
  onRowClick,
  href,
  noBorder,
  emptyMessage = "No data available.",
}: DataTableProps<T>) {
  // Build grid template from column widths
  const gridTemplate = columns.map((col) => col.width || "1fr").join(" ");

  const alignClass = (align?: "left" | "right" | "center") => {
    if (align === "right") return "text-right";
    if (align === "center") return "text-center";
    return "text-left";
  };

  return (
    <section className={noBorder ? "" : "border border-mist/10 bg-graphite/30"}>
      {/* Column headers */}
      <div
        className="grid gap-4 px-4 py-2 border-b border-mist/10 text-xs text-mist/50 uppercase tracking-wider"
        style={{ gridTemplateColumns: gridTemplate }}
      >
        {columns.map((col) => (
          <span key={col.key} className={alignClass(col.align)}>
            {col.header}
          </span>
        ))}
      </div>

      {/* Rows */}
      <div className="divide-y divide-mist/5">
        {data.length === 0 && (
          <div className="px-4 py-6 text-sm text-mist/50">
            {emptyMessage}
          </div>
        )}
        {data.map((item) => {
          const key = keyExtractor(item);
          const rowContent = (
            <div
              className="grid gap-4 px-4 py-3 items-center"
              style={{ gridTemplateColumns: gridTemplate }}
            >
              {columns.map((col) => (
                <div key={col.key} className={alignClass(col.align)}>
                  {col.render(item)}
                </div>
              ))}
            </div>
          );

          if (href) {
            return (
              <a
                key={key}
                href={href(item)}
                className="block hover:bg-slate/40 transition-colors group"
              >
                {rowContent}
              </a>
            );
          }

          if (onRowClick) {
            return (
              <div
                key={key}
                onClick={() => onRowClick(item)}
                className="hover:bg-slate/40 transition-colors group cursor-pointer"
              >
                {rowContent}
              </div>
            );
          }

          return (
            <div key={key} className="hover:bg-slate/40 transition-colors">
              {rowContent}
            </div>
          );
        })}
      </div>
    </section>
  );
}
