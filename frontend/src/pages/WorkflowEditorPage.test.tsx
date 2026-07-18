import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCreateWorkflow, useUpdateWorkflow, useWorkflow } from "@/hooks/useWorkflows";
import type { WorkflowDetailDTO } from "@/types/api";
import { WorkflowEditorPage } from "./WorkflowEditorPage";

vi.mock("@/hooks/useWorkflows");

const mockNavigate = vi.fn();
let mockParams: { id?: string } = {};
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => mockParams,
  };
});

const mockedUseWorkflow = vi.mocked(useWorkflow);
const mockedUseCreateWorkflow = vi.mocked(useCreateWorkflow);
const mockedUseUpdateWorkflow = vi.mocked(useUpdateWorkflow);

function makeWorkflowDetail(overrides: Partial<WorkflowDetailDTO> = {}): WorkflowDetailDTO {
  return {
    id: "wf-1",
    name: "Morning Watering",
    description: "Waters the garden",
    enabled: true,
    run_count: 2,
    last_run_at: null,
    last_run_status: null,
    last_run_duration_ms: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    steps: [
      {
        id: "step-1",
        step_type: "COMMAND",
        command_type: "camera.snapshot",
        sleep_seconds: null,
        group_mode: null,
        children: [],
      },
    ],
    latest_run: null,
    ...overrides,
  };
}

describe("WorkflowEditorPage", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockParams = {};
    mockedUseCreateWorkflow.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useCreateWorkflow>);
    mockedUseUpdateWorkflow.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateWorkflow>);
    mockedUseWorkflow.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useWorkflow
    >);
  });

  it("renders in create mode with an empty form and a disabled Save button", () => {
    render(<WorkflowEditorPage />);

    expect(screen.getByText("New Workflow")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Workflow" })).toBeDisabled();
    expect(screen.getByText("Add at least one step.")).toBeInTheDocument();
  });

  it("enables Save once a name and a valid step are present, then creates the workflow", async () => {
    const createMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseCreateWorkflow.mockReturnValue({
      mutateAsync: createMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useCreateWorkflow>);

    const user = userEvent.setup();
    render(<WorkflowEditorPage />);

    await user.type(screen.getByLabelText("Name"), "Evening Routine");
    await user.click(screen.getByRole("button", { name: "Add Command" }));
    await user.type(screen.getByLabelText("Command type"), "camera.snapshot");

    const saveButton = screen.getByRole("button", { name: "Save Workflow" });
    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    expect(createMutateAsync).toHaveBeenCalledWith({
      name: "Evening Routine",
      description: null,
      enabled: true,
      steps: [
        {
          step_type: "COMMAND",
          command_type: "camera.snapshot",
          sleep_seconds: null,
          group_mode: null,
          children: [],
        },
      ],
    });
    expect(mockNavigate).toHaveBeenCalledWith("/workflows");
  });

  it("hydrates the form from an existing workflow in edit mode, and updates on save", async () => {
    mockParams = { id: "wf-1" };
    mockedUseWorkflow.mockReturnValue({
      data: makeWorkflowDetail(),
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflow>);
    const updateMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseUpdateWorkflow.mockReturnValue({
      mutateAsync: updateMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateWorkflow>);

    const user = userEvent.setup();
    render(<WorkflowEditorPage />);

    expect(screen.getByText("Edit Workflow")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Morning Watering");
    expect(screen.getByLabelText("Command type")).toHaveValue("camera.snapshot");

    await user.click(screen.getByRole("button", { name: "Save Workflow" }));

    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: "wf-1",
      request: {
        name: "Morning Watering",
        description: "Waters the garden",
        enabled: true,
        steps: [
          {
            step_type: "COMMAND",
            command_type: "camera.snapshot",
            sleep_seconds: null,
            group_mode: null,
            children: [],
          },
        ],
      },
    });
    expect(mockNavigate).toHaveBeenCalledWith("/workflows");
  });

  it("shows a loading message while an existing workflow is being fetched", () => {
    mockParams = { id: "wf-1" };
    mockedUseWorkflow.mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<
      typeof useWorkflow
    >);

    render(<WorkflowEditorPage />);

    expect(screen.getByText("Loading workflow…")).toBeInTheDocument();
  });
});
