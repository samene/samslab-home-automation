import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  iconClassName?: string;
}

/** Sam's Lab's mark: a small gradient badge, shared by the sidebar and top bar. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-device text-primary-foreground shadow-sm",
        className,
      )}
    >
      <Zap className="size-5" fill="currentColor" strokeWidth={1.5} />
    </div>
  );
}

export function Logo({ className, iconClassName }: LogoProps) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark className={iconClassName} />
      <div className="leading-tight">
        <p className="text-sm font-semibold tracking-tight">Sam's Lab</p>
        <p className="text-[11px] text-muted-foreground">Mission Control</p>
      </div>
    </div>
  );
}
