import type { ReactNode } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-gradient-backdrop flex h-svh">
      {/* Visually hidden until focused — the first Tab stop for a keyboard
          user, letting them skip the nav/topbar and land straight in the
          page content instead of tabbing through every nav link first. */}
      <a
        href="#main-content"
        className="sr-only rounded-lg bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[100]"
      >
        Skip to main content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main
          id="main-content"
          tabIndex={-1}
          className="min-h-0 flex-1 pb-[env(safe-area-inset-bottom)] focus:outline-none"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
