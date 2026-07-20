import { Camera, Droplets, Radio } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { CommandStatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { useCommand } from "@/hooks/useCommands";
import { formatDuration, formatRelativeTime, formatTimestamp, friendlyCommandLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CommandDTO } from "@/types/api";

interface RecentActivityProps {
  commands: CommandDTO[];
  deviceNameById: Record<string, string>;
}

interface ActivityVisual {
  icon: LucideIcon;
  colorClass: string;
}

function visualForCommandType(commandType: string): ActivityVisual {
  if (commandType.startsWith("camera.")) return { icon: Camera, colorClass: "bg-camera/10 text-camera" };
  if (commandType.startsWith("pump.") || commandType.startsWith("water."))
    return { icon: Droplets, colorClass: "bg-water/10 text-water" };
  return { icon: Radio, colorClass: "bg-command/10 text-command" };
}

export function RecentActivity({ commands, deviceNameById }: RecentActivityProps) {
  const navigate = useNavigate();

  if (commands.length === 0) {
    return <p className="p-6 text-center text-sm text-muted-foreground">No activity yet.</p>;
  }

  return (
    <Accordion type="single" collapsible className="px-1">
      {commands.slice(0, 4).map((command) => {
        const { icon: Icon, colorClass } = visualForCommandType(command.command_type);
        return (
          <AccordionItem key={command.id} value={command.id}>
            <AccordionTrigger className="px-1.5 py-2">
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-lg", colorClass)}>
                  <Icon className="size-3.5" />
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="block truncate text-xs font-medium">
                    {friendlyCommandLabel(command.command_type)}
                  </span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    <span>{deviceNameById[command.device_id] ?? command.device_id}</span> ·{" "}
                    <span>{formatRelativeTime(command.created_at)}</span>
                  </span>
                </span>
                <CommandStatusBadge status={command.status} className="shrink-0 px-1.5 py-0 text-[10px]" />
              </span>
            </AccordionTrigger>
            <AccordionContent className="px-1.5">
              <ActivityDetail commandId={command.id} />
            </AccordionContent>
          </AccordionItem>
        );
      })}
      <button
        type="button"
        onClick={() => navigate("/history")}
        className="mt-1 w-full rounded-lg py-2 text-center text-xs font-medium text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        View all activity
      </button>
    </Accordion>
  );
}

function ActivityDetail({ commandId }: { commandId: string }) {
  const { data: command, isLoading } = useCommand(commandId);

  if (isLoading || !command) {
    return (
      <div className="flex flex-col gap-2 pl-9">
        <Skeleton className="h-3.5 w-1/2" />
        <Skeleton className="h-3.5 w-1/3" />
      </div>
    );
  }

  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 pl-9 text-[11px]">
      <div>
        <dt className="text-muted-foreground">Created</dt>
        <dd className="font-medium">{formatTimestamp(command.created_at)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Duration</dt>
        <dd className="font-medium">{formatDuration(command.result?.duration_ms)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Retries</dt>
        <dd className="font-medium">
          {command.retry_count} / {command.max_retries}
        </dd>
      </div>
      {command.result?.error_message ? (
        <div className="col-span-full">
          <dt className="text-muted-foreground">Error</dt>
          <dd className="font-medium text-destructive">{command.result.error_message}</dd>
        </div>
      ) : null}
    </dl>
  );
}
