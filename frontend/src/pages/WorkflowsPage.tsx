import { Copy, MoreVertical, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
import { Skeleton } from "@/components/ui/skeleton";
import { WorkflowExecutionStatus } from "@/components/workflows/WorkflowExecutionStatus";
import {
  useDeleteWorkflow,
  useDuplicateWorkflow,
  useRunWorkflow,
  useWorkflow,
  useWorkflows,
} from "@/hooks/useWorkflows";
import { formatRelativeTime, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { WorkflowDTO } from "@/types/api";

const PAGE_SIZE = 20;

export function WorkflowsPage() {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleteArtifacts, setDeleteArtifacts] = useState(false);

  const { data: workflowsPage, isLoading } = useWorkflows({ offset, limit: PAGE_SIZE });
  const deleteWorkflow = useDeleteWorkflow();
  const runWorkflow = useRunWorkflow();
  const duplicateWorkflow = useDuplicateWorkflow();

  const workflows = workflowsPage?.items ?? [];
  const total = workflowsPage?.total ?? 0;
  const hasNextPage = offset + PAGE_SIZE < total;
  const hasPreviousPage = offset > 0;
  const pendingDeleteWorkflow = workflows.find((workflow) => workflow.id === pendingDeleteId);

  async function handleConfirmDelete() {
    if (!pendingDeleteId) return;
    await deleteWorkflow.mutateAsync({ id: pendingDeleteId, deleteArtifacts });
    setPendingDeleteId(null);
    setDeleteArtifacts(false);
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Workflows</h1>
            <p className="text-sm text-muted-foreground">
              Composed sequences of commands, sleeps, and parallel groups.
            </p>
          </div>
          <Button type="button" className="rounded-xl" onClick={() => navigate("/workflows/new")}>
            <Plus className="size-4" />
            New Workflow
          </Button>
        </div>

        {isLoading ? (
          <CardGridSkeleton count={5} />
        ) : workflows.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">No workflows yet.</p>
        ) : (
          <Accordion type="single" collapsible className="flex flex-col gap-3">
            {workflows.map((workflow) => (
              <WorkflowRow
                key={workflow.id}
                workflow={workflow}
                onEdit={() => navigate(`/workflows/${workflow.id}/edit`)}
                onRun={() => runWorkflow.mutate(workflow.id)}
                onDuplicate={() => duplicateWorkflow.mutate(workflow.id)}
                onRequestDelete={() => setPendingDeleteId(workflow.id)}
              />
            ))}
          </Accordion>
        )}

        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {total === 0
              ? "No workflows"
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
        title="Delete this workflow?"
        description={
          pendingDeleteWorkflow ? (
            <div className="flex flex-col gap-3">
              <span>Permanently remove &ldquo;{pendingDeleteWorkflow.name}&rdquo;.</span>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={deleteArtifacts}
                  onChange={(event) => setDeleteArtifacts(event.target.checked)}
                  className="size-4 rounded border-input accent-primary"
                />
                Also delete snapshots generated by this workflow
              </label>
            </div>
          ) : (
            ""
          )
        }
        confirmLabel="Delete"
        variant="destructive"
        isConfirming={deleteWorkflow.isPending}
        onConfirm={() => void handleConfirmDelete()}
      />
    </div>
  );
}

interface WorkflowRowProps {
  workflow: WorkflowDTO;
  onEdit: () => void;
  onRun: () => void;
  onDuplicate: () => void;
  onRequestDelete: () => void;
}

function WorkflowRow({ workflow, onEdit, onRun, onDuplicate, onRequestDelete }: WorkflowRowProps) {
  return (
    <AccordionItem
      value={workflow.id}
      className="overflow-hidden rounded-2xl border border-border bg-card px-4 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-center gap-2">
        <AccordionTrigger data-testid="workflow-row" className="flex-1">
          <span className="flex min-w-0 flex-1 items-center gap-3">
            <span className="min-w-0 flex-1 text-left">
              <span className="block truncate text-sm font-semibold">{workflow.name}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {workflow.description || "No description"}
              </span>
            </span>
            <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
              {formatRelativeTime(workflow.last_run_at)}
            </span>
            {workflow.last_run_status ? (
              <WorkflowRunStatusBadge status={workflow.last_run_status} />
            ) : null}
            <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
              {workflow.run_count} run{workflow.run_count === 1 ? "" : "s"}
            </span>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                workflow.enabled
                  ? "bg-success/10 text-success"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {workflow.enabled ? "Enabled" : "Disabled"}
            </span>
          </span>
        </AccordionTrigger>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              aria-label="Workflow actions"
            >
              <MoreVertical className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem disabled={workflow.last_run_status === "RUNNING"} onClick={onRun}>
              <Play className="size-4" />
              Run Now
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onEdit}>
              <Pencil className="size-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onDuplicate}>
              <Copy className="size-4" />
              Duplicate
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

      <AccordionContent>
        <WorkflowRowDetail workflowId={workflow.id} />
      </AccordionContent>
    </AccordionItem>
  );
}

function WorkflowRowDetail({ workflowId }: { workflowId: string }) {
  const { data: workflow, isLoading } = useWorkflow(workflowId);

  if (isLoading || !workflow) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (!workflow.latest_run) {
    return <p className="text-sm text-muted-foreground">This workflow has never been run.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        Started {formatTimestamp(workflow.latest_run.started_at)}
        {workflow.latest_run.completed_at
          ? ` · Completed ${formatTimestamp(workflow.latest_run.completed_at)}`
          : ""}
      </p>
      {workflow.latest_run.error_message ? (
        <p className="rounded-lg bg-destructive/10 p-2 text-xs text-destructive">
          {workflow.latest_run.error_message}
        </p>
      ) : null}
      <WorkflowExecutionStatus stepRuns={workflow.latest_run.step_runs} />
    </div>
  );
}
