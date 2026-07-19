import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useDeleteSchedule,
  useDisableSchedule,
  useEnableSchedule,
  useRunScheduleNow,
  useSchedules,
} from "@/hooks/useSchedules";
import type { ScheduleDTO } from "@/types/api";
import { SchedulesPage } from "./SchedulesPage";

vi.mock("@/hooks/useSchedules");

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockedUseSchedules = vi.mocked(useSchedules);
const mockedUseDeleteSchedule = vi.mocked(useDeleteSchedule);
const mockedUseRunScheduleNow = vi.mocked(useRunScheduleNow);
const mockedUseEnableSchedule = vi.mocked(useEnableSchedule);
const mockedUseDisableSchedule = vi.mocked(useDisableSchedule);

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
    last_run_at: "2026-01-15T10:00:00Z",
    next_run_at: "2026-01-15T10:05:00Z",
    last_status: "COMPLETED",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SchedulesPage />
    </MemoryRouter>,
  );
}

describe("SchedulesPage", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockedUseDeleteSchedule.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSchedule>);
    mockedUseRunScheduleNow.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRunScheduleNow>);
    mockedUseEnableSchedule.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useEnableSchedule>);
    mockedUseDisableSchedule.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useDisableSchedule>);
  });

  it("shows a loading skeleton while fetching", () => {
    mockedUseSchedules.mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<
      typeof useSchedules
    >);

    renderPage();

    expect(screen.getByText("Schedules")).toBeInTheDocument();
  });

  it("shows an empty state when there are no schedules", () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    renderPage();

    expect(screen.getByText("No schedules yet.")).toBeInTheDocument();
  });

  it("renders a schedule row with its name, workflow, type, trigger, next/last run, status, and run count", () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [makeSchedule()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    renderPage();

    expect(screen.getByText("Every five minutes")).toBeInTheDocument();
    expect(screen.getByText("Nightly patrol")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Cron")).toBeInTheDocument();
    expect(screen.getByText("*/5 * * * *")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("3 runs")).toBeInTheDocument();
  });

  it("shows Disabled for a disabled schedule", () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [makeSchedule({ enabled: false })], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    renderPage();

    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });

  it("navigates to /schedules/new when New Schedule is clicked", async () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /new schedule/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/schedules/new");
  });

  it("runs, edits, disables, and deletes a schedule via the row menu", async () => {
    const runMutate = vi.fn();
    const disableMutate = vi.fn();
    const deleteMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseRunScheduleNow.mockReturnValue({ mutate: runMutate, isPending: false } as unknown as ReturnType<
      typeof useRunScheduleNow
    >);
    mockedUseDisableSchedule.mockReturnValue({
      mutate: disableMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useDisableSchedule>);
    mockedUseDeleteSchedule.mockReturnValue({
      mutateAsync: deleteMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSchedule>);
    mockedUseSchedules.mockReturnValue({
      data: { items: [makeSchedule()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Schedule actions" }));
    await user.click(await screen.findByText("Run Now"));
    expect(runMutate).toHaveBeenCalledWith("sched-1");

    await user.click(screen.getByRole("button", { name: "Schedule actions" }));
    await user.click(await screen.findByText("Disable"));
    expect(disableMutate).toHaveBeenCalledWith("sched-1");

    await user.click(screen.getByRole("button", { name: "Schedule actions" }));
    await user.click(await screen.findByText("Edit"));
    expect(mockNavigate).toHaveBeenCalledWith("/schedules/sched-1/edit");

    await user.click(screen.getByRole("button", { name: "Schedule actions" }));
    await user.click(await screen.findByText("Delete"));
    expect(screen.getByText(/Permanently remove/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteMutateAsync).toHaveBeenCalledWith({ id: "sched-1", deleteArtifacts: false });
  });

  it("shows Enable in the row menu for a disabled schedule", async () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [makeSchedule({ enabled: false })], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Schedule actions" }));
    expect(await screen.findByText("Enable")).toBeInTheDocument();
  });

  it("passes deleteArtifacts: true when the cascade-delete checkbox is checked", async () => {
    const deleteMutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteSchedule.mockReturnValue({
      mutateAsync: deleteMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteSchedule>);
    mockedUseSchedules.mockReturnValue({
      data: { items: [makeSchedule()], total: 1, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Schedule actions" }));
    await user.click(await screen.findByText("Delete"));
    await user.click(
      screen.getByText(/Also delete workflow executions, commands, and snapshots/),
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(deleteMutateAsync).toHaveBeenCalledWith({ id: "sched-1", deleteArtifacts: true });
  });

  it("enables Next when there are more pages", () => {
    const items = Array.from({ length: 20 }, (_, index) => makeSchedule({ id: `sched-${index}` }));
    mockedUseSchedules.mockReturnValue({
      data: { items, total: 45, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useSchedules>);

    renderPage();

    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });
});
