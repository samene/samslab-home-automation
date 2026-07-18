import { Ban, CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { WorkflowStepRunStatusBadge } from "@/components/shared/StatusBadge";
import { cn } from "@/lib/utils";
import type { WorkflowStepRunDTO, WorkflowStepRunStatus } from "@/types/api";

interface WorkflowExecutionStatusProps {
  stepRuns: WorkflowStepRunDTO[];
}

const STATUS_ICON: Record<WorkflowStepRunStatus, LucideIcon> = {
  PENDING: CircleDashed,
  RUNNING: Loader2,
  COMPLETED: CheckCircle2,
  FAILED: XCircle,
  CANCELLED: Ban,
};

const STATUS_ICON_CLASS: Record<WorkflowStepRunStatus, string> = {
  PENDING: "text-muted-foreground opacity-50",
  RUNNING: "text-primary animate-spin",
  COMPLETED: "text-success",
  FAILED: "text-destructive",
  CANCELLED: "text-muted-foreground",
};

function stepTypeLabel(stepRun: WorkflowStepRunDTO): string {
  if (stepRun.step_type === "COMMAND") return "Command Task";
  if (stepRun.step_type === "SLEEP") return "Sleep";
  return "Parallel Group";
}

/** "N/M complete" for a group step-run — counts children that reached COMPLETED against the total. */
function completionProgress(children: WorkflowStepRunDTO[]): { done: number; total: number } {
  const done = children.filter((child) => child.status === "COMPLETED").length;
  return { done, total: children.length };
}

export function WorkflowExecutionStatus({ stepRuns }: WorkflowExecutionStatusProps) {
  if (stepRuns.length === 0) {
    return <p className="text-sm text-muted-foreground">No steps have run yet.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {stepRuns.map((stepRun) => (
        <StepRunNode key={stepRun.workflow_step_id} stepRun={stepRun} />
      ))}
    </div>
  );
}

function StepRunNode({ stepRun }: { stepRun: WorkflowStepRunDTO }) {
  const Icon = STATUS_ICON[stepRun.status];
  const isGroup = stepRun.step_type === "GROUP";
  const progress = isGroup ? completionProgress(stepRun.children) : null;

  return (
    <div
      data-testid="step-run-node"
      className={cn(
        "rounded-xl border border-border p-3",
        stepRun.status === "RUNNING" && "border-primary/50 bg-primary/5",
        stepRun.status === "PENDING" && "opacity-60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className={cn("size-4 shrink-0", STATUS_ICON_CLASS[stepRun.status])} />
          <span className="truncate text-sm font-medium">{stepTypeLabel(stepRun)}</span>
          {progress ? (
            <span className="text-xs text-muted-foreground">
              ({progress.done}/{progress.total} complete)
            </span>
          ) : null}
        </div>
        <WorkflowStepRunStatusBadge status={stepRun.status} />
      </div>

      {stepRun.status === "FAILED" && stepRun.error_message ? (
        <p className="mt-2 rounded-lg bg-destructive/10 p-2 text-xs text-destructive">
          {stepRun.error_message}
        </p>
      ) : null}

      {stepRun.children.length > 0 ? (
        <div className="mt-2 flex flex-col gap-2 border-l border-border pl-3">
          {stepRun.children.map((child) => (
            <StepRunNode key={child.workflow_step_id} stepRun={child} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
