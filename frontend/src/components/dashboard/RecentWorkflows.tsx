import { Play } from "lucide-react";
import { WorkflowRunStatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRunWorkflow, useWorkflows } from "@/hooks/useWorkflows";
import { formatDuration } from "@/lib/format";
import type { WorkflowDTO } from "@/types/api";

/** Self-contained, mirroring how RecentSnapshots fetches its own data internally. */
export function RecentWorkflows() {
  const { data: workflowsPage } = useWorkflows();
  const runWorkflow = useRunWorkflow();

  const recentWorkflows = [...(workflowsPage?.items ?? [])]
    .filter((workflow): workflow is WorkflowDTO & { last_run_at: string } => workflow.last_run_at !== null)
    .sort((a, b) => new Date(b.last_run_at).getTime() - new Date(a.last_run_at).getTime())
    .slice(0, 3);

  return (
    <Card className="flex shrink-0 flex-col gap-2 p-3">
      <h3 className="px-1 text-xs font-semibold">Recent Workflows</h3>
      {recentWorkflows.length === 0 ? (
        <p className="px-1 py-2 text-center text-xs text-muted-foreground">No workflow runs yet.</p>
      ) : (
        <div className="flex flex-col gap-1">
          {recentWorkflows.map((workflow) => (
            <div key={workflow.id} className="flex items-center gap-2 rounded-lg px-1 py-0.5 text-xs">
              <span className="min-w-0 flex-1 truncate font-medium">{workflow.name}</span>
              <span className="shrink-0 text-muted-foreground">
                {formatDuration(workflow.last_run_duration_ms)}
              </span>
              {workflow.last_run_status ? (
                <WorkflowRunStatusBadge status={workflow.last_run_status} />
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-6 shrink-0"
                disabled={workflow.last_run_status === "RUNNING" || runWorkflow.isPending}
                onClick={() => runWorkflow.mutate(workflow.id)}
                aria-label={`Run ${workflow.name} now`}
              >
                <Play className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
