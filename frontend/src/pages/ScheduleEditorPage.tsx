import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateSchedule, useSchedule, useUpdateSchedule } from "@/hooks/useSchedules";
import { useWorkflows } from "@/hooks/useWorkflows";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ScheduleType } from "@/types/api";

function supportedTimezones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin"];
  }
}

export function ScheduleEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isEditMode = Boolean(id);
  const navigate = useNavigate();

  const { data: existingSchedule, isLoading } = useSchedule(id);
  const { data: workflowsPage } = useWorkflows({ limit: 100 });
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [scheduleType, setScheduleType] = useState<ScheduleType>("CRON");
  const [cronExpression, setCronExpression] = useState("");
  const [runAt, setRunAt] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [hasHydrated, setHasHydrated] = useState(false);

  const timezones = useMemo(() => supportedTimezones(), []);
  const workflows = workflowsPage?.items ?? [];

  useEffect(() => {
    if (isEditMode && existingSchedule && !hasHydrated) {
      setName(existingSchedule.name);
      setDescription(existingSchedule.description ?? "");
      setWorkflowId(existingSchedule.workflow_id);
      setEnabled(existingSchedule.enabled);
      setScheduleType(existingSchedule.schedule_type);
      setCronExpression(existingSchedule.cron_expression ?? "");
      setRunAt(existingSchedule.run_at ? existingSchedule.run_at.slice(0, 16) : "");
      setTimezone(existingSchedule.timezone);
      setHasHydrated(true);
    }
  }, [isEditMode, existingSchedule, hasHydrated]);

  const isValid =
    name.trim().length > 0 &&
    workflowId.length > 0 &&
    (scheduleType === "CRON" ? cronExpression.trim().length > 0 : runAt.length > 0);
  const isSaving = createSchedule.isPending || updateSchedule.isPending;

  async function handleSave() {
    const request = {
      workflow_id: workflowId,
      name: name.trim(),
      description: description.trim() || null,
      enabled,
      schedule_type: scheduleType,
      cron_expression: scheduleType === "CRON" ? cronExpression.trim() : null,
      run_at: scheduleType === "ONE_TIME" ? runAt : null,
      timezone,
    };

    if (isEditMode && id) {
      await updateSchedule.mutateAsync({ id, request });
    } else {
      await createSchedule.mutateAsync(request);
    }
    navigate("/schedules");
  }

  if (isEditMode && isLoading && !hasHydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Loading schedule…</div>;
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {isEditMode ? "Edit Schedule" : "New Schedule"}
          </h1>
          <p className="text-sm text-muted-foreground">
            Trigger an existing workflow once at a specific time, or on a recurring cadence.
          </p>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="schedule-name">Name</Label>
            <Input
              id="schedule-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Nightly patrol"
              className={cn(!name.trim() && "border-destructive")}
            />
            {!name.trim() ? <p className="text-xs text-destructive">Name is required.</p> : null}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="schedule-description">Description</Label>
            <Input
              id="schedule-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="schedule-workflow">Workflow</Label>
            <select
              id="schedule-workflow"
              value={workflowId}
              onChange={(event) => setWorkflowId(event.target.value)}
              className={cn(
                "h-9 rounded-md border border-input bg-transparent px-3 text-sm shadow-xs",
                !workflowId && "border-destructive",
              )}
            >
              <option value="" disabled>
                Select a workflow…
              </option>
              {workflows.map((workflow) => (
                <option key={workflow.id} value={workflow.id}>
                  {workflow.name}
                </option>
              ))}
            </select>
            {!workflowId ? (
              <p className="text-xs text-destructive">A workflow is required.</p>
            ) : null}
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              className="size-4 rounded border-input accent-primary"
            />
            Enabled
          </label>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Trigger</h2>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setScheduleType("ONE_TIME")}
              className={cn(
                "flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                scheduleType === "ONE_TIME"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              One Time
            </button>
            <button
              type="button"
              onClick={() => setScheduleType("CRON")}
              className={cn(
                "flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                scheduleType === "CRON"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              Cron
            </button>
          </div>

          {scheduleType === "ONE_TIME" ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="schedule-run-at">Date &amp; time</Label>
              <Input
                id="schedule-run-at"
                type="datetime-local"
                value={runAt}
                onChange={(event) => setRunAt(event.target.value)}
              />
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="schedule-cron">Cron expression</Label>
              <Input
                id="schedule-cron"
                value={cronExpression}
                onChange={(event) => setCronExpression(event.target.value)}
                placeholder="*/5 * * * *"
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                Standard 5-field crontab syntax (minute hour day month weekday).
              </p>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="schedule-timezone">Timezone</Label>
            <select
              id="schedule-timezone"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
              className="h-9 rounded-md border border-input bg-transparent px-3 text-sm shadow-xs"
            >
              {timezones.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>

          {isEditMode && existingSchedule?.next_run_at ? (
            <p className="text-xs text-muted-foreground">
              Next run: {formatTimestamp(existingSchedule.next_run_at)}
            </p>
          ) : null}
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => navigate("/schedules")}>
            Cancel
          </Button>
          <Button type="button" disabled={!isValid || isSaving} onClick={() => void handleSave()}>
            {isSaving ? "Saving…" : "Save Schedule"}
          </Button>
        </div>
      </div>
    </div>
  );
}
