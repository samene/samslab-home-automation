import { WorkflowRunStatusBadge } from "@/components/shared/StatusBadge";
import { Card } from "@/components/ui/card";
import { useSchedules } from "@/hooks/useSchedules";
import { formatCountdown, formatTimestamp } from "@/lib/format";

/** Self-contained, mirroring how RecentWorkflows/RecentSnapshots fetch their own data internally. */
export function UpcomingSchedules() {
  const { data: schedulesPage } = useSchedules({ enabled: true, limit: 5 });
  const upcoming = (schedulesPage?.items ?? []).filter((schedule) => schedule.next_run_at !== null);

  return (
    <Card className="flex shrink-0 flex-col gap-2 p-3">
      <h3 className="px-1 text-xs font-semibold">Upcoming Schedules</h3>
      {upcoming.length === 0 ? (
        <p className="px-1 py-2 text-center text-xs text-muted-foreground">No upcoming schedules.</p>
      ) : (
        <div className="flex flex-col gap-1">
          {upcoming.map((schedule) => (
            <div key={schedule.id} className="flex items-center gap-2 rounded-lg px-1 py-0.5 text-xs">
              <span className="min-w-0 flex-1 truncate font-medium">
                {schedule.workflow_name ?? schedule.workflow_id}
              </span>
              <span className="shrink-0 text-muted-foreground">
                {formatTimestamp(schedule.next_run_at)}
              </span>
              <span className="shrink-0 font-medium text-primary">
                {formatCountdown(schedule.next_run_at)}
              </span>
              {schedule.last_status ? (
                <WorkflowRunStatusBadge status={schedule.last_status} />
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
