import type {
  WorkflowGroupMode,
  WorkflowStepCreateRequest,
  WorkflowStepDTO,
  WorkflowStepType,
} from "@/types/api";

/** The currently-real command types — a starting point for the datalist, not an exhaustive list (free text is still accepted). */
export const KNOWN_COMMAND_TYPES = [
  "camera.stream.start",
  "camera.stream.stop",
  "camera.snapshot",
  "camera.record.start",
  "camera.record.stop",
  // No duration parameter here or anywhere in a workflow step: the timer
  // relay wired to the pump's GPIO line owns watering duration, not the Pi
  // — see docs/agent/PUMP.md.
  "pump.trigger",
];

/** A step as edited in local state — plain values (never null) so inputs stay controlled, converted to/from the wire shape at the editor's boundary. */
export interface EditableStep {
  localId: string;
  step_type: WorkflowStepType;
  command_type: string;
  sleep_seconds: number;
  group_mode: WorkflowGroupMode | null;
  children: EditableStep[];
}

let localIdCounter = 0;
function generateLocalId(): string {
  localIdCounter += 1;
  return `local-step-${localIdCounter}`;
}

export function createCommandStep(): EditableStep {
  return {
    localId: generateLocalId(),
    step_type: "COMMAND",
    command_type: "",
    sleep_seconds: 1,
    group_mode: null,
    children: [],
  };
}

export function createSleepStep(): EditableStep {
  return {
    localId: generateLocalId(),
    step_type: "SLEEP",
    command_type: "",
    sleep_seconds: 1,
    group_mode: null,
    children: [],
  };
}

export function createParallelGroupStep(): EditableStep {
  return {
    localId: generateLocalId(),
    step_type: "GROUP",
    command_type: "",
    sleep_seconds: 1,
    group_mode: "PARALLEL",
    children: [createCommandStep(), createCommandStep()],
  };
}

export function cloneStep(step: EditableStep): EditableStep {
  return {
    ...step,
    localId: generateLocalId(),
    children: step.children.map(cloneStep),
  };
}

export function stepDtoToEditable(step: WorkflowStepDTO): EditableStep {
  return {
    localId: step.id,
    step_type: step.step_type,
    command_type: step.command_type ?? "",
    sleep_seconds: step.sleep_seconds ?? 1,
    group_mode: step.group_mode,
    children: step.children.map(stepDtoToEditable),
  };
}

export function editableToRequest(step: EditableStep): WorkflowStepCreateRequest {
  return {
    step_type: step.step_type,
    command_type: step.step_type === "COMMAND" ? step.command_type : null,
    sleep_seconds: step.step_type === "SLEEP" ? step.sleep_seconds : null,
    group_mode: step.step_type === "GROUP" ? step.group_mode : null,
    children: step.step_type === "GROUP" ? step.children.map(editableToRequest) : [],
  };
}

/** Per-step validation messages, keyed by localId. Does not check "at least one top-level step" — that's a whole-list concern the caller (the editor page) checks separately. */
export function validateSteps(steps: EditableStep[]): Record<string, string> {
  const errors: Record<string, string> = {};

  function walk(list: EditableStep[]) {
    for (const step of list) {
      if (step.step_type === "COMMAND" && !step.command_type.trim()) {
        errors[step.localId] = "Command type is required";
      } else if (
        step.step_type === "SLEEP" &&
        (!Number.isFinite(step.sleep_seconds) || step.sleep_seconds < 1)
      ) {
        errors[step.localId] = "Must be at least 1 second";
      } else if (step.step_type === "GROUP") {
        const minChildren = step.group_mode === "PARALLEL" ? 2 : 1;
        if (step.children.length < minChildren) {
          errors[step.localId] =
            step.group_mode === "PARALLEL"
              ? "Parallel groups need at least 2 steps"
              : "Groups need at least 1 step";
        }
        walk(step.children);
      }
    }
  }

  walk(steps);
  return errors;
}

export function isWorkflowStepsValid(steps: EditableStep[]): boolean {
  return steps.length > 0 && Object.keys(validateSteps(steps)).length === 0;
}

export function labelForStep(step: EditableStep): string {
  if (step.step_type === "COMMAND") return "Command Task";
  if (step.step_type === "SLEEP") return "Sleep";
  return step.group_mode === "PARALLEL" ? "Parallel Group" : "Group";
}
