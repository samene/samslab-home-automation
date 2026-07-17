import {
  Activity,
  AlarmClock,
  CheckCircle2,
  CircleDot,
  Loader2,
  Radio,
  Server,
  ShieldAlert,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { CommandStatusBadge, DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { useCommands } from "@/hooks/useCommands";
import { useDispatcherStatistics, useDispatcherStatus } from "@/hooks/useDispatcher";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CommandDTO, DeviceDTO } from "@/types/api";

interface SystemStatusPanelProps {
  device: DeviceDTO | undefined;
  latestCommand: CommandDTO | undefined;
}

interface StatRowProps {
  icon: typeof Activity;
  label: string;
  value: React.ReactNode;
}

function StatRow({ icon: Icon, label, value }: StatRowProps) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </span>
      <span className="text-xs font-medium">{value}</span>
    </div>
  );
}

export function SystemStatusPanel({ device, latestCommand }: SystemStatusPanelProps) {
  const dispatcherStatus = useDispatcherStatus();
  const dispatcherStatistics = useDispatcherStatistics();
  const completedCommands = useCommands({ status: "COMPLETED", limit: 1 });

  const isRestricted = dispatcherStatus.isError || dispatcherStatistics.isError;

  return (
    <Card className="flex shrink-0 flex-col gap-1 p-3">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-xs font-semibold">System Status</h3>
        <Badge
          variant={dispatcherStatus.data?.running ? "success" : "outline"}
          className="gap-1 rounded-full px-1.5 py-0 text-[10px]"
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              dispatcherStatus.data?.running ? "animate-pulse bg-success-foreground" : "bg-muted-foreground",
            )}
          />
          {dispatcherStatus.data?.running ? "Running" : "Idle"}
        </Badge>
      </div>

      <StatRow
        icon={Radio}
        label="Current Command"
        value={latestCommand?.command_type ?? "—"}
      />
      <StatRow
        icon={CircleDot}
        label="Current Command Status"
        value={latestCommand ? <CommandStatusBadge status={latestCommand.status} /> : "—"}
      />
      <StatRow icon={Server} label="Connected Device" value={device?.display_name ?? "—"} />
      <StatRow
        icon={Activity}
        label="Connection Status"
        value={device ? <DeviceStatusBadge status={device.status} /> : "—"}
      />
      <StatRow
        icon={AlarmClock}
        label="Last Message from Device"
        value={formatRelativeTime(device?.last_seen)}
      />

      <div className="my-1 h-px bg-border" />

      {isRestricted ? (
        <div className="flex items-center gap-1.5 rounded-lg bg-muted px-2 py-1.5 text-[11px] text-muted-foreground">
          <ShieldAlert className="size-3.5 shrink-0" />
          Requires an administrator account.
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-1.5 text-center">
          <MiniStat
            icon={Loader2}
            label="Pending"
            value={dispatcherStatistics.data?.queue_depth}
            spin
          />
          <MiniStat icon={Activity} label="Running" value={dispatcherStatistics.data?.running_count} />
          <MiniStat icon={CheckCircle2} label="Completed" value={completedCommands.data?.total} />
        </div>
      )}
    </Card>
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
  spin,
}: {
  icon: typeof Activity;
  label: string;
  value: number | undefined;
  spin?: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-0.5 rounded-lg bg-muted px-1.5 py-1.5">
      <Icon className={cn("size-3.5 text-muted-foreground", spin && (value ?? 0) > 0 && "animate-spin")} />
      <span className="text-sm font-semibold tabular-nums">{value ?? "—"}</span>
      <span className="text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}
