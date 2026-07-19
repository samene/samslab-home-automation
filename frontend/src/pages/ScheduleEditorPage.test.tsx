import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCreateSchedule, useSchedule, useUpdateSchedule } from "@/hooks/useSchedules";
import { useWorkflows } from "@/hooks/useWorkflows";
import type { ScheduleDTO } from "@/types/api";
import { ScheduleEditorPage } from "./ScheduleEditorPage";

vi.mock("@/hooks/useSchedules");
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

const mockedUseSchedule = vi.mocked(useSchedule);
const mockedUseCreateSchedule = vi.mocked(useCreateSchedule);
const mockedUseUpdateSchedule = vi.mocked(useUpdateSchedule);
const mockedUseWorkflows = vi.mocked(useWorkflows);

function makeSchedule(overrides: Partial<ScheduleDTO> = {}): ScheduleDTO {
  return {
    id: "sched-1",
    workflow_id: "wf-1",
    workflow_name: "Nightly patrol",
    name: "Every five minutes",
    description: "Runs often",
    enabled: true,
    schedule_type: "CRON",
    cron_expression: "*/5 * * * *",
    run_at: null,
    timezone: "UTC",
    run_count: 3,
    last_run_at: null,
    next_run_at: "2026-01-15T10:05:00Z",
    last_status: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ScheduleEditorPage", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockParams = {};
    mockedUseCreateSchedule.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useCreateSchedule>);
    mockedUseUpdateSchedule.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateSchedule>);
    mockedUseSchedule.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useSchedule
    >);
    mockedUseWorkflows.mockReturnValue({
      data: {
        items: [{ id: "wf-1", name: "Nightly patrol" }, { id: "wf-2", name: "Morning Watering" }],
        total: 2,
        offset: 0,
        limit: 100,
      },
    } as unknown as ReturnType<typeof useWorkflows>);
  });

  it("renders in create mode with an empty form and a disabled Save button", () => {
    render(<ScheduleEditorPage />);

    expect(screen.getByText("New Schedule")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Schedule" })).toBeDisabled();
  });

  it("defaults to Cron and shows the cron input", () => {
    render(<ScheduleEditorPage />);

    expect(screen.getByLabelText("Cron expression")).toBeInTheDocument();
    expect(screen.queryByLabelText("Date & time")).not.toBeInTheDocument();
  });

  it("switches to the one-time date/time input when One Time is selected", async () => {
    const user = userEvent.setup();
    render(<ScheduleEditorPage />);

    await user.click(screen.getByRole("button", { name: "One Time" }));

    expect(screen.getByLabelText("Date & time")).toBeInTheDocument();
    expect(screen.queryByLabelText("Cron expression")).not.toBeInTheDocument();
  });

  it("enables Save once name, workflow, and cron are present, then creates the schedule", async () => {
    const createMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseCreateSchedule.mockReturnValue({
      mutateAsync: createMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useCreateSchedule>);

    const user = userEvent.setup();
    render(<ScheduleEditorPage />);

    await user.type(screen.getByLabelText("Name"), "Nightly run");
    await user.selectOptions(screen.getByLabelText("Workflow"), "wf-1");
    await user.type(screen.getByLabelText("Cron expression"), "*/5 * * * *");

    const saveButton = screen.getByRole("button", { name: "Save Schedule" });
    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    expect(createMutateAsync).toHaveBeenCalledWith({
      workflow_id: "wf-1",
      name: "Nightly run",
      description: null,
      enabled: true,
      schedule_type: "CRON",
      cron_expression: "*/5 * * * *",
      run_at: null,
      timezone: "UTC",
    });
    expect(mockNavigate).toHaveBeenCalledWith("/schedules");
  });

  it("hydrates the form from an existing schedule in edit mode, and updates on save", async () => {
    mockParams = { id: "sched-1" };
    mockedUseSchedule.mockReturnValue({
      data: makeSchedule(),
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedule>);
    const updateMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseUpdateSchedule.mockReturnValue({
      mutateAsync: updateMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateSchedule>);

    const user = userEvent.setup();
    render(<ScheduleEditorPage />);

    expect(screen.getByText("Edit Schedule")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Every five minutes");
    expect(screen.getByLabelText("Cron expression")).toHaveValue("*/5 * * * *");

    await user.click(screen.getByRole("button", { name: "Save Schedule" }));

    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: "sched-1",
      request: {
        workflow_id: "wf-1",
        name: "Every five minutes",
        description: "Runs often",
        enabled: true,
        schedule_type: "CRON",
        cron_expression: "*/5 * * * *",
        run_at: null,
        timezone: "UTC",
      },
    });
    expect(mockNavigate).toHaveBeenCalledWith("/schedules");
  });

  it("shows a loading message while an existing schedule is being fetched", () => {
    mockParams = { id: "sched-1" };
    mockedUseSchedule.mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<
      typeof useSchedule
    >);

    render(<ScheduleEditorPage />);

    expect(screen.getByText("Loading schedule…")).toBeInTheDocument();
  });
});
