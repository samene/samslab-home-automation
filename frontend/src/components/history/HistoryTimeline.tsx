import { Ban, Camera, Droplets, Radio, Trash2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { CommandStatusBadge } from "@/components/shared/StatusBadge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCancelCommand, useCommand, useDeleteCommand } from "@/hooks/useCommands";
import { useScheduleExecutions } from "@/hooks/useSchedules";
import { formatDuration, formatTimestamp, friendlyCommandLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CommandDTO, CommandStatus } from "@/types/api";

/** Mirrors the server's `TERMINAL_STATUSES` (server/app/domains/commands/models.py) —
 * only a command in one of these can be deleted; anything else must be
 * cancelled first.
 */
const TERMINAL_STATUSES = new Set<CommandStatus>([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "EXPIRED",
  "TIMEOUT",
]);

/** Builds a workflow_run_id -> schedule_name lookup from every recorded firing.
 *
 * A command whose correlation_id isn't in this map was triggered manually
 * (either a direct command, or a manually-run workflow) — there is no
 * separate "manual" record to look up, it's simply the absence of a match.
 */
function useScheduleNameByRunId(): Map<string, string> {
  const { data } = useScheduleExecutions({ limit: 100 });
  const map = new Map<string, string>();
  for (const execution of data?.items ?? []) {
    if (execution.workflow_run_id && execution.schedule_name) {
      map.set(execution.workflow_run_id, execution.schedule_name);
    }
  }
  return map;
}

interface HistoryTimelineProps {
  commands: CommandDTO[];
  deviceNameById: Record<string, string>;
  selectionMode: boolean;
  selectedIds: Set<string>;
  onToggleSelect: (commandId: string) => void;
}

interface Visual {
  icon: LucideIcon;
  colorClass: string;
}

function visualForCommandType(commandType: string): Visual {
  if (commandType.startsWith("camera.")) return { icon: Camera, colorClass: "bg-camera/10 text-camera" };
  if (commandType.startsWith("pump.") || commandType.startsWith("water."))
    return { icon: Droplets, colorClass: "bg-water/10 text-water" };
  return { icon: Radio, colorClass: "bg-command/10 text-command" };
}

export function HistoryTimeline({
  commands,
  deviceNameById,
  selectionMode,
  selectedIds,
  onToggleSelect,
}: HistoryTimelineProps) {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);
  const deleteCommand = useDeleteCommand();
  const cancelCommand = useCancelCommand();
  const scheduleNameByRunId = useScheduleNameByRunId();

  if (commands.length === 0) {
    return <p className="p-8 text-center text-sm text-muted-foreground">No activity found.</p>;
  }

  const pendingDeleteCommand = commands.find((command) => command.id === pendingDeleteId);
  const pendingCancelCommand = commands.find((command) => command.id === pendingCancelId);

  async function handleConfirmDelete() {
    if (!pendingDeleteId) return;
    await deleteCommand.mutateAsync(pendingDeleteId);
    setPendingDeleteId(null);
  }

  async function handleConfirmCancel() {
    if (!pendingCancelId) return;
    await cancelCommand.mutateAsync({ commandId: pendingCancelId });
    setPendingCancelId(null);
  }

  return (
    <>
      <Accordion type="single" collapsible className="flex flex-col gap-3">
        {commands.map((command) => {
          const { icon: Icon, colorClass } = visualForCommandType(command.command_type);
          const scheduleName = scheduleNameByRunId.get(command.correlation_id);
          return (
            <AccordionItem
              key={command.id}
              value={command.id}
              className="overflow-hidden rounded-2xl border border-border bg-card px-4 shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="flex items-center gap-1">
                {selectionMode ? (
                  <label className="flex size-11 shrink-0 cursor-pointer items-center justify-center">
                    <input
                      type="checkbox"
                      aria-label={`Select ${command.command_type}`}
                      className="size-4 shrink-0 rounded border-input accent-primary coarse:size-5"
                      checked={selectedIds.has(command.id)}
                      onChange={() => onToggleSelect(command.id)}
                    />
                  </label>
                ) : null}
                <AccordionTrigger data-testid="history-row" className="flex-1">
                  <span className="flex min-w-0 flex-1 items-center gap-3">
                    <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", colorClass)}>
                      <Icon className="size-5" />
                    </span>
                    <span className="min-w-0 flex-1 text-left">
                      <span className="block truncate text-sm font-semibold">
                        {friendlyCommandLabel(command.command_type)}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        <span>{deviceNameById[command.device_id] ?? command.device_id}</span> ·{" "}
                        <span>{formatTimestamp(command.created_at)}</span> ·{" "}
                        <span>{scheduleName ? `Scheduled via ${scheduleName}` : "Manual"}</span>
                      </span>
                    </span>
                    <CommandStatusBadge status={command.status} />
                  </span>
                </AccordionTrigger>
              </div>
              <AccordionContent>
                <HistoryCardDetail
                  commandId={command.id}
                  scheduleName={scheduleName}
                  onRequestDelete={() => setPendingDeleteId(command.id)}
                  onRequestCancel={() => setPendingCancelId(command.id)}
                />
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>

      <ConfirmDialog
        open={pendingDeleteId !== null}
        onOpenChange={(open) => !open && setPendingDeleteId(null)}
        title="Delete this activity?"
        description={
          pendingDeleteCommand
            ? `Permanently remove "${pendingDeleteCommand.command_type}" from history. Only finished commands can be deleted.`
            : ""
        }
        confirmLabel="Delete"
        variant="destructive"
        isConfirming={deleteCommand.isPending}
        onConfirm={() => void handleConfirmDelete()}
      />

      <ConfirmDialog
        open={pendingCancelId !== null}
        onOpenChange={(open) => !open && setPendingCancelId(null)}
        title="Cancel this command?"
        description={
          pendingCancelCommand
            ? `Stop "${pendingCancelCommand.command_type}" from running further. It can be deleted from history afterward.`
            : ""
        }
        confirmLabel="Cancel Command"
        variant="destructive"
        isConfirming={cancelCommand.isPending}
        onConfirm={() => void handleConfirmCancel()}
      />
    </>
  );
}

function HistoryCardDetail({
  commandId,
  scheduleName,
  onRequestDelete,
  onRequestCancel,
}: {
  commandId: string;
  scheduleName: string | undefined;
  onRequestDelete: () => void;
  onRequestCancel: () => void;
}) {
  const { data: command, isLoading } = useCommand(commandId);

  if (isLoading || !command) {
    return (
      <div className="flex flex-col gap-2 pl-[3.25rem]">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 pl-0 text-sm sm:pl-[3.25rem]">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Field label="Duration">{formatDuration(command.result?.duration_ms)}</Field>
        <Field label="Completed">{formatTimestamp(command.completed_at)}</Field>
        <Field label="Retries">
          {command.retry_count} / {command.max_retries}
        </Field>
        <Field label="Triggered By">{scheduleName ? `Scheduled via ${scheduleName}` : "Manual"}</Field>
      </dl>

      {command.result?.error_message ? (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Error</p>
          <p className="rounded-xl bg-destructive/10 p-2.5 text-destructive">
            {command.result.error_message}
          </p>
        </div>
      ) : null}

      {command.result ? (
        <details className="group rounded-xl bg-muted p-2.5">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none group-open:mb-2">
            Result (JSON)
          </summary>
          <pre className="max-h-48 overflow-auto text-xs">
            {JSON.stringify(command.result.result, null, 2)}
          </pre>
        </details>
      ) : null}

      <div className="flex justify-end">
        {TERMINAL_STATUSES.has(command.status) ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={onRequestDelete}
          >
            <Trash2 className="size-3.5" />
            Delete
          </Button>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={onRequestCancel}
          >
            <Ban className="size-3.5" />
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}
