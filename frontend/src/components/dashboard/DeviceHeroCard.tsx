import { Cpu } from "lucide-react";
import { Card } from "@/components/ui/card";
import { DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/format";
import type { DeviceDTO } from "@/types/api";

interface DeviceHeroCardProps {
  device: DeviceDTO | undefined;
}

export function DeviceHeroCard({ device }: DeviceHeroCardProps) {
  const isOnline = device?.status === "ONLINE";

  return (
    <Card
      className="relative flex shrink-0 flex-col gap-2 overflow-hidden border-none bg-gradient-to-br from-device via-primary to-camera p-3 text-primary-foreground shadow-lg"
      data-testid="device-hero-card"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_100%_0%,rgba(255,255,255,0.25),transparent_45%)]" />

      {!device ? (
        <p className="relative text-sm text-primary-foreground/80">No devices registered yet.</p>
      ) : (
        <div className="relative flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white/15 backdrop-blur-sm">
              <Cpu className="size-4" />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold tracking-tight">
                {device.display_name}
              </h2>
              <div className="flex items-center gap-1.5 text-[11px] text-primary-foreground/85">
                <span className="relative flex size-1.5">
                  {isOnline ? (
                    <span className="absolute inline-flex size-full animate-ping rounded-full bg-white/70" />
                  ) : null}
                  <span
                    className={cn(
                      "relative inline-flex size-1.5 rounded-full",
                      isOnline ? "bg-white" : "bg-white/40",
                    )}
                  />
                </span>
                <span>{formatRelativeTime(device.last_seen)}</span>
              </div>
            </div>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-1 text-right">
            <DeviceStatusBadge status={device.status} />
            <span className="text-[11px] text-primary-foreground/70">
              {device.agent_version ?? "—"}
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}
