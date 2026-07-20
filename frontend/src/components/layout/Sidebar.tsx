import { CalendarClock, History, Images, LayoutDashboard, Settings, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router-dom";
import { Logo, LogoMark } from "@/components/layout/Logo";
import { cn } from "@/lib/utils";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

/** The single source of truth for every nav surface — desktop rail, tablet rail, and the mobile drawer all render this same list, so a route is never reachable from one and missing from another. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/history", label: "History", icon: History },
  { to: "/saved-media", label: "Saved Media", icon: Images },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/schedules", label: "Schedules", icon: CalendarClock },
  { to: "/settings", label: "Settings", icon: Settings },
];

/**
 * Full-labeled nav list — reused by the desktop sidebar (always) and the
 * mobile drawer (`MobileNavDrawer`), so both surfaces stay in sync for free.
 */
export function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1 px-3 py-2">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "group flex min-h-11 items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted-foreground transition-all hover:bg-accent hover:text-accent-foreground",
              isActive &&
                "bg-gradient-to-r from-primary to-primary/80 text-primary-foreground shadow-sm hover:from-primary hover:to-primary/80 hover:text-primary-foreground",
            )
          }
        >
          <item.icon className="size-[18px] shrink-0" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

/** Desktop: full, persistent, always-expanded (`lg:`+). Tablet (`md`–`lg`): a collapsed icon-only rail — same nav, no off-canvas panel to open. Below `md`: hidden entirely in favor of TopBar's hamburger + drawer. */
export function Sidebar() {
  return (
    <>
      <aside
        className="hidden shrink-0 flex-col items-center gap-1 border-r border-border bg-card/60 py-3 backdrop-blur-sm md:flex lg:hidden"
        aria-label="Primary"
      >
        <div className="mb-2 flex h-10 w-16 items-center justify-center">
          <LogoMark className="size-8 rounded-lg" />
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            title={item.label}
            className={({ isActive }) =>
              cn(
                "flex w-16 flex-col items-center gap-1 rounded-xl px-1 py-2 text-[10px] font-medium text-muted-foreground transition-all hover:bg-accent hover:text-accent-foreground",
                isActive && "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
              )
            }
          >
            <item.icon className="size-5 shrink-0" />
            <span className="truncate">{item.label}</span>
          </NavLink>
        ))}
      </aside>

      <aside
        className="hidden w-64 shrink-0 flex-col border-r border-border bg-card/60 backdrop-blur-sm lg:flex"
        aria-label="Primary"
      >
        <div className="flex h-16 items-center px-5">
          <Logo />
        </div>

        <NavList />

        <div className="mt-auto p-4">
          <div className="rounded-xl border border-border bg-secondary/60 p-3 text-xs text-muted-foreground">
            Everything you need is on the{" "}
            <span className="font-medium text-foreground">Dashboard</span> — live camera, controls,
            and system status all in one place.
          </div>
        </div>
      </aside>
    </>
  );
}
