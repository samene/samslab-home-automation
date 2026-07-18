import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WorkflowStepRunDTO } from "@/types/api";
import { WorkflowExecutionStatus } from "./WorkflowExecutionStatus";

function makeStepRun(overrides: Partial<WorkflowStepRunDTO> = {}): WorkflowStepRunDTO {
  return {
    id: "run-step-1",
    workflow_step_id: "step-1",
    step_type: "COMMAND",
    status: "PENDING",
    started_at: null,
    completed_at: null,
    command_id: null,
    error_message: null,
    children: [],
    ...overrides,
  };
}

describe("WorkflowExecutionStatus", () => {
  it("shows an empty-state message when there are no step runs", () => {
    render(<WorkflowExecutionStatus stepRuns={[]} />);
    expect(screen.getByText("No steps have run yet.")).toBeInTheDocument();
  });

  it("renders a step run with the right status badge and label", () => {
    render(
      <WorkflowExecutionStatus
        stepRuns={[makeStepRun({ workflow_step_id: "step-1", status: "COMPLETED" })]}
      />,
    );

    expect(screen.getByText("Command Task")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("shows the error message for a FAILED step", () => {
    render(
      <WorkflowExecutionStatus
        stepRuns={[
          makeStepRun({
            workflow_step_id: "step-1",
            status: "FAILED",
            error_message: "device unreachable",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("device unreachable")).toBeInTheDocument();
  });

  it("shows a distinct badge for a CANCELLED step", () => {
    render(
      <WorkflowExecutionStatus
        stepRuns={[makeStepRun({ workflow_step_id: "step-1", status: "CANCELLED" })]}
      />,
    );

    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });

  it("renders a GROUP step run's nested children and computes N/M complete", () => {
    const group = makeStepRun({
      workflow_step_id: "group-1",
      step_type: "GROUP",
      status: "RUNNING",
      children: [
        makeStepRun({ workflow_step_id: "child-1", status: "COMPLETED" }),
        makeStepRun({ workflow_step_id: "child-2", status: "RUNNING" }),
        makeStepRun({ workflow_step_id: "child-3", status: "PENDING" }),
      ],
    });

    render(<WorkflowExecutionStatus stepRuns={[group]} />);

    expect(screen.getByText("Parallel Group")).toBeInTheDocument();
    expect(screen.getByText("(1/3 complete)")).toBeInTheDocument();
    // Each child renders its own node too.
    expect(screen.getAllByTestId("step-run-node")).toHaveLength(4);
  });

  it("renders a Sleep step run", () => {
    render(
      <WorkflowExecutionStatus
        stepRuns={[makeStepRun({ workflow_step_id: "step-1", step_type: "SLEEP", status: "RUNNING" })]}
      />,
    );

    expect(screen.getByText("Sleep")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
