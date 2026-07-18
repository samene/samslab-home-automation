import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { WorkflowStepEditor } from "@/components/workflows/WorkflowStepEditor";
import {
  editableToRequest,
  isWorkflowStepsValid,
  stepDtoToEditable,
  type EditableStep,
} from "@/components/workflows/workflowStepModel";
import { useCreateWorkflow, useUpdateWorkflow, useWorkflow } from "@/hooks/useWorkflows";
import { cn } from "@/lib/utils";

export function WorkflowEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isEditMode = Boolean(id);
  const navigate = useNavigate();

  const { data: existingWorkflow, isLoading } = useWorkflow(id);
  const createWorkflow = useCreateWorkflow();
  const updateWorkflow = useUpdateWorkflow();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [steps, setSteps] = useState<EditableStep[]>([]);
  const [hasHydrated, setHasHydrated] = useState(false);

  useEffect(() => {
    if (isEditMode && existingWorkflow && !hasHydrated) {
      setName(existingWorkflow.name);
      setDescription(existingWorkflow.description ?? "");
      setEnabled(existingWorkflow.enabled);
      setSteps(existingWorkflow.steps.map(stepDtoToEditable));
      setHasHydrated(true);
    }
  }, [isEditMode, existingWorkflow, hasHydrated]);

  const isValid = name.trim().length > 0 && isWorkflowStepsValid(steps);
  const isSaving = createWorkflow.isPending || updateWorkflow.isPending;

  async function handleSave() {
    const request = {
      name: name.trim(),
      description: description.trim() || null,
      enabled,
      steps: steps.map(editableToRequest),
    };

    if (isEditMode && id) {
      await updateWorkflow.mutateAsync({ id, request });
    } else {
      await createWorkflow.mutateAsync(request);
    }
    navigate("/workflows");
  }

  if (isEditMode && isLoading && !hasHydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Loading workflow…</div>;
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {isEditMode ? "Edit Workflow" : "New Workflow"}
          </h1>
          <p className="text-sm text-muted-foreground">
            Compose a serial sequence of commands, sleeps, and parallel groups.
          </p>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="workflow-name">Name</Label>
            <Input
              id="workflow-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Morning Watering"
              className={cn(!name.trim() && "border-destructive")}
            />
            {!name.trim() ? <p className="text-xs text-destructive">Name is required.</p> : null}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="workflow-description">Description</Label>
            <Input
              id="workflow-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional"
            />
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

        <div className="rounded-2xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">Steps</h2>
          <WorkflowStepEditor steps={steps} onChange={setSteps} />
          {steps.length === 0 ? (
            <p className="mt-2 text-xs text-destructive">Add at least one step.</p>
          ) : null}
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => navigate("/workflows")}>
            Cancel
          </Button>
          <Button type="button" disabled={!isValid || isSaving} onClick={() => void handleSave()}>
            {isSaving ? "Saving…" : "Save Workflow"}
          </Button>
        </div>
      </div>
    </div>
  );
}
