import { ChevronDown, ChevronUp, Copy, Plus, Trash2 } from "lucide-react";
import { WorkflowStepIcon } from "@/components/workflows/WorkflowStepIcon";
import {
  KNOWN_COMMAND_TYPES,
  cloneStep,
  createCommandStep,
  createParallelGroupStep,
  createSleepStep,
  labelForStep,
  validateSteps,
  type EditableStep,
} from "@/components/workflows/workflowStepModel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function Connector() {
  return (
    <div className="flex justify-center py-1 text-muted-foreground" aria-hidden="true">
      <ChevronDown className="size-4" />
    </div>
  );
}

interface StepCardProps {
  step: EditableStep;
  error?: string;
  errors: Record<string, string>;
  onChange: (step: EditableStep) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
}

function StepCard({
  step,
  error,
  errors,
  onChange,
  onMoveUp,
  onMoveDown,
  onDuplicate,
  onDelete,
  canMoveUp,
  canMoveDown,
}: StepCardProps) {
  return (
    <Card className="p-3">
      <div className="flex items-start gap-3">
        <WorkflowStepIcon stepType={step.step_type} groupMode={step.group_mode} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span data-testid="step-label" className="text-sm font-semibold">
              {labelForStep(step)}
            </span>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={!canMoveUp}
                onClick={onMoveUp}
                aria-label="Move step up"
              >
                <ChevronUp className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={!canMoveDown}
                onClick={onMoveDown}
                aria-label="Move step down"
              >
                <ChevronDown className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                onClick={onDuplicate}
                aria-label="Duplicate step"
              >
                <Copy className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7 text-destructive hover:text-destructive"
                onClick={onDelete}
                aria-label="Delete step"
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          </div>

          {step.step_type === "COMMAND" ? (
            <div className="mt-2">
              <Input
                list="known-commands"
                placeholder="e.g. camera.snapshot"
                aria-label="Command type"
                value={step.command_type}
                onChange={(event) => onChange({ ...step, command_type: event.target.value })}
                className={cn(error && "border-destructive")}
              />
              {error ? <p className="mt-1 text-xs text-destructive">{error}</p> : null}
            </div>
          ) : null}

          {step.step_type === "SLEEP" ? (
            <div className="mt-2 flex items-center gap-2">
              <Input
                type="number"
                min={1}
                aria-label="Sleep seconds"
                value={step.sleep_seconds}
                onChange={(event) => onChange({ ...step, sleep_seconds: Number(event.target.value) })}
                className={cn("w-28", error && "border-destructive")}
              />
              <span className="text-xs text-muted-foreground">seconds</span>
              {error ? <p className="text-xs text-destructive">{error}</p> : null}
            </div>
          ) : null}

          {step.step_type === "GROUP" ? (
            <div className="mt-3 rounded-xl border border-dashed border-border p-3">
              {error ? <p className="mb-2 text-xs text-destructive">{error}</p> : null}
              <StepList
                steps={step.children}
                onChange={(children) => onChange({ ...step, children })}
                allowGroups={false}
                errors={errors}
              />
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

interface StepListProps {
  steps: EditableStep[];
  onChange: (steps: EditableStep[]) => void;
  allowGroups: boolean;
  errors: Record<string, string>;
}

function StepList({ steps, onChange, allowGroups, errors }: StepListProps) {
  function updateStep(index: number, updated: EditableStep) {
    const next = [...steps];
    next[index] = updated;
    onChange(next);
  }

  function moveStep(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  function duplicateStep(index: number) {
    const next = [...steps];
    next.splice(index + 1, 0, cloneStep(steps[index]));
    onChange(next);
  }

  function deleteStep(index: number) {
    onChange(steps.filter((_, i) => i !== index));
  }

  function addStep(step: EditableStep) {
    onChange([...steps, step]);
  }

  return (
    <div className="flex flex-col">
      {steps.map((step, index) => (
        <div key={step.localId} className="flex flex-col">
          {index > 0 ? <Connector /> : null}
          <StepCard
            step={step}
            error={errors[step.localId]}
            errors={errors}
            onChange={(updated) => updateStep(index, updated)}
            onMoveUp={() => moveStep(index, -1)}
            onMoveDown={() => moveStep(index, 1)}
            onDuplicate={() => duplicateStep(index)}
            onDelete={() => deleteStep(index)}
            canMoveUp={index > 0}
            canMoveDown={index < steps.length - 1}
          />
        </div>
      ))}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => addStep(createCommandStep())}>
          <Plus className="size-3.5" />
          Add Command
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => addStep(createSleepStep())}>
          <Plus className="size-3.5" />
          Add Sleep
        </Button>
        {allowGroups ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => addStep(createParallelGroupStep())}
          >
            <Plus className="size-3.5" />
            Add Parallel Group
          </Button>
        ) : null}
      </div>
    </div>
  );
}

interface WorkflowStepEditorProps {
  steps: EditableStep[];
  onChange: (steps: EditableStep[]) => void;
}

export function WorkflowStepEditor({ steps, onChange }: WorkflowStepEditorProps) {
  const errors = validateSteps(steps);

  return (
    <div className="flex flex-col gap-2">
      <datalist id="known-commands">
        {KNOWN_COMMAND_TYPES.map((type) => (
          <option key={type} value={type} />
        ))}
      </datalist>

      <div className="flex justify-center">
        <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-muted-foreground">
          START
        </span>
      </div>

      {steps.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No steps yet — add a Command, Sleep, or Parallel Group step below.
        </p>
      ) : (
        <Connector />
      )}

      <StepList steps={steps} onChange={onChange} allowGroups errors={errors} />

      <Connector />
      <div className="flex justify-center">
        <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-muted-foreground">
          END
        </span>
      </div>
    </div>
  );
}
