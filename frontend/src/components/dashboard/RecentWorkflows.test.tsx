import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRunWorkflow, useWorkflows } from "@/hooks/useWorkflows";
import type { WorkflowDTO } from "@/types/api";
import { RecentWorkflows } from "./RecentWorkflows";

vi.mock("@/hooks/useWorkflows");

const mockedUseWorkflows = vi.mocked(useWorkflows);
const mockedUseRunWorkflow = vi.mocked(useRunWorkflow);

function makeWorkflow(overrides: Partial<WorkflowDTO> = {}): WorkflowDTO {
  return {
    id: "wf-1",
    name: "Morning Watering",
    description: null,
    enabled: true,
    run_count: 1,
    last_run_at: "2026-01-15T10:00:00Z",
    last_run_status: "COMPLETED",
    last_run_duration_ms: 4200,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("RecentWorkflows", () => {
  beforeEach(() => {
    mockedUseRunWorkflow.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRunWorkflow>);
  });

  it("shows an empty state when no workflow has ever run", () => {
    mockedUseWorkflows.mockReturnValue({
      data: {
        items: [makeWorkflow({ last_run_at: null, last_run_status: null })],
        total: 1,
        offset: 0,
        limit: 20,
      },
    } as unknown as ReturnType<typeof useWorkflows>);

    render(<RecentWorkflows />);

    expect(screen.getByText("No workflow runs yet.")).toBeInTheDocument();
  });

  it("shows up to the 3 most recently run workflows, newest first", () => {
    mockedUseWorkflows.mockReturnValue({
      data: {
        items: [
          makeWorkflow({ id: "wf-1", name: "Oldest", last_run_at: "2026-01-10T10:00:00Z" }),
          makeWorkflow({ id: "wf-2", name: "Newest", last_run_at: "2026-01-15T10:00:00Z" }),
          makeWorkflow({ id: "wf-3", name: "Middle", last_run_at: "2026-01-12T10:00:00Z" }),
          makeWorkflow({ id: "wf-4", name: "Never Run", last_run_at: null, last_run_status: null }),
        ],
        total: 4,
        offset: 0,
        limit: 20,
      },
    } as unknown as ReturnType<typeof useWorkflows>);

    render(<RecentWorkflows />);

    expect(screen.getByText("Newest")).toBeInTheDocument();
    expect(screen.getByText("Middle")).toBeInTheDocument();
    expect(screen.getByText("Oldest")).toBeInTheDocument();
    expect(screen.queryByText("Never Run")).not.toBeInTheDocument();
  });

  it("disables the Run Now button while a run is already RUNNING", () => {
    mockedUseWorkflows.mockReturnValue({
      data: {
        items: [makeWorkflow({ last_run_status: "RUNNING" })],
        total: 1,
        offset: 0,
        limit: 20,
      },
    } as unknown as ReturnType<typeof useWorkflows>);

    render(<RecentWorkflows />);

    expect(screen.getByRole("button", { name: /run morning watering now/i })).toBeDisabled();
  });

  it("triggers a run when the Run Now button is clicked", async () => {
    const mutate = vi.fn();
    mockedUseRunWorkflow.mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<
      typeof useRunWorkflow
    >);
    mockedUseWorkflows.mockReturnValue({
      data: { items: [makeWorkflow()], total: 1, offset: 0, limit: 20 },
    } as unknown as ReturnType<typeof useWorkflows>);

    const user = userEvent.setup();
    render(<RecentWorkflows />);

    await user.click(screen.getByRole("button", { name: /run morning watering now/i }));
    expect(mutate).toHaveBeenCalledWith("wf-1");
  });
});
