"use client";

import { ReactNode } from "react";
import Sidebar from "./Sidebar";

export default function AppShell({
  children,
  rightPanel,
}: {
  children: ReactNode;
  rightPanel?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      {/* Sidebar - always visible */}
      <aside className="flex-shrink-0 w-64 h-screen sticky top-0">
        <Sidebar />
      </aside>

      {/* Main content area */}
      <div className="flex flex-1 min-w-0">
        <main className="flex-1 min-w-0 p-6 space-y-6 overflow-x-hidden">
          {children}
        </main>

        {/* Optional right panel (ChatPanel) */}
        {rightPanel && (
          <aside className="hidden xl:block flex-shrink-0 w-[420px] h-screen sticky top-0">
            {rightPanel}
          </aside>
        )}
      </div>
    </div>
  );
}
