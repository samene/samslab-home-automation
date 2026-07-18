import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useDeleteWorkflow,
  useDuplicateWorkflow,
  useRunWorkflow,
  useWorkflow,
  useWorkflows,
} from "@/hooks/useWorkflows";
import type { WorkflowDetailDTO, WorkflowDTO } from "@/types/api";
import { WorkflowsPage } from "./WorkflowsPage";

vi.mock("@/hooks/useWorkflows");

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockedUseWorkflows = vi.mocked(useWorkflows);
const mockedUseWorkflow = vi.mocked(useWorkflow);
const mockedUseDeleteWorkflow = vi.mocked(useDeleteWorkflow);
const mockedUseRunWorkflow = vi.mocked(useRunWorkflow);
const mockedUseDuplicateWorkflow = vi.mocked(useDuplicateWorkflow);

function makeWorkflow(overrides: Partial<WorkflowDTO> = {}): WorkflowDTO {
  return {
    id: "wf-1",
    name: "Morning Watering",
    description: "Waters the garden every morning",
    enabled: true,
    run_count: 3,
    last_run_at: "2026-01-15T10:00:00Z",
    last_run_status: "COMPLETED",
    last_run_duration_ms: 4200,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeWorkflowDetail(overrides: Partial<WorkflowDetailDTO> = {}): WorkflowDetailDTO {
  return {
    ...makeWorkflow(),
    steps: [],
    latest_run: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <WorkflowsPage />
    </MemoryRouter>,
  );
}

describe("WorkflowsPage", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockedUseDeleteWorkflow.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteWorkflow>);
    mockedUseRunWorkflow.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRunWorkflow>);
    mockedUseDuplicateWorkflow.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useDuplicateWorkflow>);
    mockedUseWorkflow.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useWorkflow
    >);
  });

  it("shows a loading skeleton while fetching", () => {
    mockedUseWorkflows.mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<
      typeof useWorkflows
    >);

    renderPage();

    expect(screen.getByText("Workflows")).toBeInTheDocument();
  });

  it("shows an empty state when there are no workflows", () => {
    mockedUseWorkflows.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    renderPage();

    expect(screen.getByText("No workflows yet.")).toBeInTheDocument();
  });

  it("renders a workflow row with its name, description, status badge, and run count", () => {
    mockedUseWorkflows.mockReturnValue({
      data: { items: [makeWorkflow()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    renderPage();

    expect(screen.getByText("Morning Watering")).toBeInTheDocument();
    expect(screen.getByText("Waters the garden every morning")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("3 runs")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("shows Disabled for a disabled workflow with no runs yet", () => {
    mockedUseWorkflows.mockReturnValue({
      data: {
        items: [makeWorkflow({ enabled: false, run_count: 0, last_run_at: null, last_run_status: null })],
        total: 1,
        offset: 0,
        limit: 20,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    renderPage();

    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText("0 runs")).toBeInTheDocument();
  });

  it("enables Next when there are more pages", () => {
    const items = Array.from({ length: 20 }, (_, index) => makeWorkflow({ id: `wf-${index}` }));
    mockedUseWorkflows.mockReturnValue({
      data: { items, total: 45, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    renderPage();

    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("navigates to /workflows/new when New Workflow is clicked", async () => {
    mockedUseWorkflows.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /new workflow/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/workflows/new");
  });

  it("runs, edits, duplicates, and deletes a workflow via the row menu", async () => {
    const runMutate = vi.fn();
    const duplicateMutate = vi.fn();
    const deleteMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseRunWorkflow.mockReturnValue({ mutate: runMutate, isPending: false } as unknown as ReturnType<
      typeof useRunWorkflow
    >);
    mockedUseDuplicateWorkflow.mockReturnValue({
      mutate: duplicateMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useDuplicateWorkflow>);
    mockedUseDeleteWorkflow.mockReturnValue({
      mutateAsync: deleteMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteWorkflow>);
    mockedUseWorkflows.mockReturnValue({
      data: { items: [makeWorkflow()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Workflow actions" }));
    await user.click(await screen.findByText("Run Now"));
    expect(runMutate).toHaveBeenCalledWith("wf-1");

    await user.click(screen.getByRole("button", { name: "Workflow actions" }));
    await user.click(await screen.findByText("Edit"));
    expect(mockNavigate).toHaveBeenCalledWith("/workflows/wf-1/edit");

    await user.click(screen.getByRole("button", { name: "Workflow actions" }));
    await user.click(await screen.findByText("Duplicate"));
    expect(duplicateMutate).toHaveBeenCalledWith("wf-1");

    await user.click(screen.getByRole("button", { name: "Workflow actions" }));
    await user.click(await screen.findByText("Delete"));
    expect(screen.getByText(/Permanently remove.*Morning Watering/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteMutateAsync).toHaveBeenCalledWith({ id: "wf-1", deleteArtifacts: false });
  });

  it("passes deleteArtifacts: true when the 'also delete snapshots' checkbox is checked", async () => {
    const deleteMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteWorkflow.mockReturnValue({
      mutateAsync: deleteMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteWorkflow>);
    mockedUseWorkflows.mockReturnValue({
      data: { items: [makeWorkflow()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Workflow actions" }));
    await user.click(await screen.findByText("Delete"));
    await user.click(screen.getByText(/Also delete snapshots generated by this workflow/));

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteMutateAsync).toHaveBeenCalledWith({ id: "wf-1", deleteArtifacts: true });
  });

  it("disables Run Now while a run is already in progress", async () => {
    mockedUseWorkflows.mockReturnValue({
      data: {
        items: [makeWorkflow({ last_run_status: "RUNNING" })],
        total: 1,
        offset: 0,
        limit: 20,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Workflow actions" }));
    expect(await screen.findByText("Run Now")).toHaveAttribute("data-disabled");
  });

  it("expands a row to show live execution status via useWorkflow", async () => {
    mockedUseWorkflows.mockReturnValue({
      data: { items: [makeWorkflow()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);
    mockedUseWorkflow.mockReturnValue({
      data: makeWorkflowDetail({
        latest_run: {
          id: "run-1",
          workflow_id: "wf-1",
          status: "COMPLETED",
          started_at: "2026-01-15T10:00:00Z",
          completed_at: "2026-01-15T10:00:05Z",
          error_message: null,
          step_runs: [
            {
              id: "run-step-1",
              workflow_step_id: "step-1",
              step_type: "COMMAND",
              status: "COMPLETED",
              started_at: "2026-01-15T10:00:00Z",
              completed_at: "2026-01-15T10:00:02Z",
              command_id: "cmd-1",
              error_message: null,
              children: [],
            },
          ],
        },
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflow>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByTestId("workflow-row"));
    expect(await screen.findByText("Command Task")).toBeInTheDocument();
  });

  it("shows a 'never run' message when a row is expanded with no latest run", async () => {
    mockedUseWorkflows.mockReturnValue({
      data: { items: [makeWorkflow({ last_run_at: null, last_run_status: null })], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflows>);
    mockedUseWorkflow.mockReturnValue({
      data: makeWorkflowDetail({ latest_run: null }),
      isLoading: false,
    } as unknown as ReturnType<typeof useWorkflow>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByTestId("workflow-row"));
    expect(await screen.findByText("This workflow has never been run.")).toBeInTheDocument();
  });
});
