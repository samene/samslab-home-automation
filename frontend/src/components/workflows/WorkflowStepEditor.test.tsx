import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { WorkflowStepDTO } from "@/types/api";
import {
  editableToRequest,
  isWorkflowStepsValid,
  stepDtoToEditable,
  validateSteps,
  type EditableStep,
} from "./workflowStepModel";
import { WorkflowStepEditor } from "./WorkflowStepEditor";

function Harness({ initialSteps = [] }: { initialSteps?: EditableStep[] }) {
  const [steps, setSteps] = useState<EditableStep[]>(initialSteps);
  return <WorkflowStepEditor steps={steps} onChange={setSteps} />;
}

describe("WorkflowStepEditor", () => {
  it("shows an empty state and START/END markers with no steps", () => {
    render(<Harness />);
    expect(screen.getByText("START")).toBeInTheDocument();
    expect(screen.getByText("END")).toBeInTheDocument();
    expect(screen.getByText(/No steps yet/)).toBeInTheDocument();
  });

  it("adds a Command step", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Command" }));

    expect(screen.getByText("Command Task")).toBeInTheDocument();
    expect(screen.getByLabelText("Command type")).toBeInTheDocument();
  });

  it("adds a Sleep step with a numeric seconds field", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Sleep" }));

    expect(screen.getByText("Sleep")).toBeInTheDocument();
    expect(screen.getByLabelText("Sleep seconds")).toBeInTheDocument();
  });

  it("adds a Parallel Group with 2 child steps by default, and no nested group option", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Parallel Group" }));

    expect(screen.getByText("Parallel Group")).toBeInTheDocument();
    expect(screen.getAllByText("Command Task")).toHaveLength(2);
    // Only one "Add Parallel Group" button should exist (top-level only, not inside the nested list).
    expect(screen.getAllByRole("button", { name: "Add Parallel Group" })).toHaveLength(1);
  });

  it("deletes a step", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Command" }));
    expect(screen.getByText("Command Task")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete step" }));
    expect(screen.queryByText("Command Task")).not.toBeInTheDocument();
    expect(screen.getByText(/No steps yet/)).toBeInTheDocument();
  });

  it("duplicates a step", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Command" }));
    await user.click(screen.getByRole("button", { name: "Duplicate step" }));

    expect(screen.getAllByText("Command Task")).toHaveLength(2);
    expect(screen.getAllByLabelText("Command type")).toHaveLength(2);
  });

  it("moves a step up and down, disabling at the boundaries", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Command" }));
    await user.click(screen.getByRole("button", { name: "Add Sleep" }));

    const cards = screen.getAllByTestId("step-label");
    expect(cards.map((el) => el.textContent)).toEqual(["Command Task", "Sleep"]);

    const moveUpButtons = screen.getAllByRole("button", { name: "Move step up" });
    const moveDownButtons = screen.getAllByRole("button", { name: "Move step down" });

    // First card can't move up, second can't move down.
    expect(moveUpButtons[0]).toBeDisabled();
    expect(moveDownButtons[1]).toBeDisabled();

    await user.click(moveDownButtons[0]);

    const reordered = screen.getAllByTestId("step-label");
    expect(reordered.map((el) => el.textContent)).toEqual(["Sleep", "Command Task"]);
  });

  it("shows an inline validation message for an empty command type", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Command" }));

    expect(screen.getByText("Command type is required")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Command type"), "camera.snapshot");
    expect(screen.queryByText("Command type is required")).not.toBeInTheDocument();
  });

  it("shows an inline validation message when a parallel group drops below 2 children", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add Parallel Group" }));
    const groupCard = screen.getByText("Parallel Group").closest("div.p-3") as HTMLElement;
    // Index 0 is the group step's own delete button; index 1+ belong to its two child steps.
    const deleteButtons = within(groupCard).getAllByRole("button", { name: "Delete step" });
    await user.click(deleteButtons[1]);

    expect(screen.getByText("Parallel groups need at least 2 steps")).toBeInTheDocument();
  });
});

describe("validateSteps / isWorkflowStepsValid", () => {
  function commandStep(overrides: Partial<EditableStep> = {}): EditableStep {
    return {
      localId: "local-1",
      step_type: "COMMAND",
      command_type: "camera.snapshot",
      sleep_seconds: 1,
      group_mode: null,
      children: [],
      ...overrides,
    };
  }

  it("is invalid with zero top-level steps", () => {
    expect(isWorkflowStepsValid([])).toBe(false);
  });

  it("is valid with a single well-formed command step", () => {
    expect(isWorkflowStepsValid([commandStep()])).toBe(true);
  });

  it("flags a command step with an empty command_type", () => {
    const errors = validateSteps([commandStep({ command_type: "" })]);
    expect(errors["local-1"]).toBe("Command type is required");
  });

  it("flags a sleep step with sleep_seconds below 1", () => {
    const errors = validateSteps([
      { ...commandStep(), step_type: "SLEEP", sleep_seconds: 0 },
    ]);
    expect(errors["local-1"]).toBe("Must be at least 1 second");
  });

  it("flags a parallel group with fewer than 2 children", () => {
    const errors = validateSteps([
      {
        localId: "group-1",
        step_type: "GROUP",
        command_type: "",
        sleep_seconds: 1,
        group_mode: "PARALLEL",
        children: [commandStep()],
      },
    ]);
    expect(errors["group-1"]).toBe("Parallel groups need at least 2 steps");
  });

  it("recurses into group children", () => {
    const errors = validateSteps([
      {
        localId: "group-1",
        step_type: "GROUP",
        command_type: "",
        sleep_seconds: 1,
        group_mode: "PARALLEL",
        children: [commandStep({ localId: "child-1", command_type: "" }), commandStep({ localId: "child-2" })],
      },
    ]);
    expect(errors["child-1"]).toBe("Command type is required");
    expect(errors["child-2"]).toBeUndefined();
  });
});

describe("stepDtoToEditable / editableToRequest", () => {
  it("round-trips a recursive step tree", () => {
    const dto: WorkflowStepDTO = {
      id: "step-1",
      step_type: "GROUP",
      command_type: null,
      sleep_seconds: null,
      group_mode: "PARALLEL",
      children: [
        {
          id: "step-1a",
          step_type: "COMMAND",
          command_type: "camera.snapshot",
          sleep_seconds: null,
          group_mode: null,
          children: [],
        },
        {
          id: "step-1b",
          step_type: "SLEEP",
          command_type: null,
          sleep_seconds: 5,
          group_mode: null,
          children: [],
        },
      ],
    };

    const editable = stepDtoToEditable(dto);
    expect(editable.localId).toBe("step-1");
    expect(editable.children).toHaveLength(2);

    const request = editableToRequest(editable);
    expect(request).toEqual({
      step_type: "GROUP",
      command_type: null,
      sleep_seconds: null,
      group_mode: "PARALLEL",
      children: [
        {
          step_type: "COMMAND",
          command_type: "camera.snapshot",
          sleep_seconds: null,
          group_mode: null,
          children: [],
        },
        {
          step_type: "SLEEP",
          command_type: null,
          sleep_seconds: 5,
          group_mode: null,
          children: [],
        },
      ],
    });
  });
});
