import { Ban, CalendarClock, MoreVertical, Pencil, Play, Power, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CardGridSkeleton } from "@/components/shared/LoadingSkeleton";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { WorkflowRunStatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useDeleteSchedule,
  useDisableSchedule,
  useEnableSchedule,
  useRunScheduleNow,
  useSchedules,
} from "@/hooks/useSchedules";
import { formatCountdown, formatRelativeTime, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ScheduleDTO } from "@/types/api";

const PAGE_SIZE = 20;

export function SchedulesPage() {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleteArtifacts, setDeleteArtifacts] = useState(false);

  const { data: schedulesPage, isLoading } = useSchedules({ offset, limit: PAGE_SIZE });
  const deleteSchedule = useDeleteSchedule();
  const runScheduleNow = useRunScheduleNow();
  const enableSchedule = useEnableSchedule();
  const disableSchedule = useDisableSchedule();

  const schedules = schedulesPage?.items ?? [];
  const total = schedulesPage?.total ?? 0;
  const hasNextPage = offset + PAGE_SIZE < total;
  const hasPreviousPage = offset > 0;
  const pendingDeleteSchedule = schedules.find((schedule) => schedule.id === pendingDeleteId);

  async function handleConfirmDelete() {
    if (!pendingDeleteId) return;
    await deleteSchedule.mutateAsync({ id: pendingDeleteId, deleteArtifacts });
    setPendingDeleteId(null);
    setDeleteArtifacts(false);
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Schedules</h1>
            <p className="text-sm text-muted-foreground">
              One-time and recurring triggers that run an existing workflow.
            </p>
          </div>
          <Button type="button" className="rounded-xl" onClick={() => navigate("/schedules/new")}>
            <CalendarClock className="size-4" />
            New Schedule
          </Button>
        </div>

        {isLoading ? (
          <CardGridSkeleton count={5} />
        ) : schedules.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">No schedules yet.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {schedules.map((schedule) => (
              <ScheduleRow
                key={schedule.id}
                schedule={schedule}
                onEdit={() => navigate(`/schedules/${schedule.id}/edit`)}
                onRun={() => runScheduleNow.mutate(schedule.id)}
                onEnable={() => enableSchedule.mutate(schedule.id)}
                onDisable={() => disableSchedule.mutate(schedule.id)}
                onRequestDelete={() => setPendingDeleteId(schedule.id)}
              />
            ))}
          </div>
        )}

        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {total === 0
              ? "No schedules"
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={!hasPreviousPage}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="rounded-lg"
              disabled={!hasNextPage}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={pendingDeleteId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDeleteId(null);
            setDeleteArtifacts(false);
          }
        }}
        title="Delete this schedule?"
        description={
          pendingDeleteSchedule ? (
            <div className="flex flex-col gap-3">
              <span>Permanently remove &ldquo;{pendingDeleteSchedule.name}&rdquo;.</span>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={deleteArtifacts}
                  onChange={(event) => setDeleteArtifacts(event.target.checked)}
                  className="size-4 rounded border-input accent-primary coarse:size-5"
                />
                Also delete workflow executions, commands, and snapshots this schedule generated
              </label>
            </div>
          ) : (
            ""
          )
        }
        confirmLabel="Delete"
        variant="destructive"
        isConfirming={deleteSchedule.isPending}
        onConfirm={() => void handleConfirmDelete()}
      />
    </div>
  );
}

interface ScheduleRowProps {
  schedule: ScheduleDTO;
  onEdit: () => void;
  onRun: () => void;
  onEnable: () => void;
  onDisable: () => void;
  onRequestDelete: () => void;
}

function ScheduleRow({ schedule, onEdit, onRun, onEnable, onDisable, onRequestDelete }: ScheduleRowProps) {
  const triggerLabel =
    schedule.schedule_type === "CRON"
      ? (schedule.cron_expression ?? "—")
      : formatTimestamp(schedule.run_at);

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-card px-4 py-3 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold">{schedule.name}</span>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                schedule.enabled ? "bg-success/10 text-success" : "bg-muted text-muted-foreground",
              )}
            >
              {schedule.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {schedule.workflow_name ?? schedule.workflow_id}
          </p>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              aria-label="Schedule actions"
            >
              <MoreVertical className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onRun}>
              <Play className="size-4" />
              Run Now
            </DropdownMenuItem>
            {schedule.enabled ? (
              <DropdownMenuItem onClick={onDisable}>
                <Ban className="size-4" />
                Disable
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onClick={onEnable}>
                <Power className="size-4" />
                Enable
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={onEdit}>
              <Pencil className="size-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={onRequestDelete}
            >
              <Trash2 className="size-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="rounded-md bg-muted px-1.5 py-0.5 font-medium text-foreground">
          {schedule.schedule_type === "CRON" ? "Cron" : "One Time"}
        </span>
        <span>{triggerLabel}</span>
        <span>·</span>
        <span>Next run: {formatCountdown(schedule.next_run_at)}</span>
        <span>·</span>
        <span>Last run: {formatRelativeTime(schedule.last_run_at)}</span>
        {schedule.last_status ? (
          <>
            <span>·</span>
            <WorkflowRunStatusBadge status={schedule.last_status} />
          </>
        ) : null}
        <span>·</span>
        <span>
          {schedule.run_count} run{schedule.run_count === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}
