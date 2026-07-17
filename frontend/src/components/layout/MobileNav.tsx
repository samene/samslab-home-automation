import { History, LayoutDashboard, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/history", label: "History", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];

/** Bottom tab bar shown only below the `sm` breakpoint, mirroring the sidebar's nav. */
export function MobileNav() {
  return (
    <nav className="flex shrink-0 items-center justify-around border-t border-border bg-card/80 py-2 backdrop-blur-sm sm:hidden">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          className={({ isActive }) =>
            cn(
              "flex flex-col items-center gap-1 rounded-lg px-4 py-1.5 text-[11px] font-medium text-muted-foreground",
              isActive && "text-primary",
            )
          }
        >
          <item.icon className="size-5" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
