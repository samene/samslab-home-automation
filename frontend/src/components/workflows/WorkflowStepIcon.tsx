import { Clock, GitBranch, Split, Terminal } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkflowGroupMode, WorkflowStepType } from "@/types/api";

interface WorkflowStepIconProps {
  stepType: WorkflowStepType;
  groupMode?: WorkflowGroupMode | null;
  className?: string;
}

function iconFor(stepType: WorkflowStepType, groupMode?: WorkflowGroupMode | null): LucideIcon {
  if (stepType === "COMMAND") return Terminal;
  if (stepType === "SLEEP") return Clock;
  return groupMode === "PARALLEL" ? Split : GitBranch;
}

function colorClassFor(stepType: WorkflowStepType): string {
  if (stepType === "COMMAND") return "bg-command/10 text-command";
  if (stepType === "SLEEP") return "bg-secondary text-secondary-foreground";
  return "bg-camera/10 text-camera";
}

export function WorkflowStepIcon({ stepType, groupMode, className }: WorkflowStepIconProps) {
  const Icon = iconFor(stepType, groupMode);
  return (
    <span
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-xl",
        colorClassFor(stepType),
        className,
      )}
    >
      <Icon className="size-4" />
    </span>
  );
}
