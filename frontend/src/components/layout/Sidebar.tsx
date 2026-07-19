import { CalendarClock, History, Images, LayoutDashboard, Settings, Workflow } from "lucide-react";
import { NavLink } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/history", label: "History", icon: History },
  { to: "/snapshots", label: "Snapshots", icon: Images },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/schedules", label: "Schedules", icon: CalendarClock },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-card/60 backdrop-blur-sm sm:flex">
      <div className="flex h-16 items-center px-5">
        <Logo />
      </div>

      <nav className="flex flex-col gap-1 px-3 py-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted-foreground transition-all hover:bg-accent hover:text-accent-foreground",
                isActive &&
                  "bg-gradient-to-r from-primary to-primary/80 text-primary-foreground shadow-sm hover:from-primary hover:to-primary/80 hover:text-primary-foreground",
              )
            }
          >
            <item.icon className="size-[18px]" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto p-4">
        <div className="rounded-xl border border-border bg-secondary/60 p-3 text-xs text-muted-foreground">
          Everything you need is on the{" "}
          <span className="font-medium text-foreground">Dashboard</span> — live camera, controls,
          and system status all in one place.
        </div>
      </div>
    </aside>
  );
}
