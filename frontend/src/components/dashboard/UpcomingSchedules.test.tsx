import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useSchedules } from "@/hooks/useSchedules";
import type { ScheduleDTO } from "@/types/api";
import { UpcomingSchedules } from "./UpcomingSchedules";

vi.mock("@/hooks/useSchedules");

const mockedUseSchedules = vi.mocked(useSchedules);

function makeSchedule(overrides: Partial<ScheduleDTO> = {}): ScheduleDTO {
  return {
    id: "sched-1",
    workflow_id: "wf-1",
    workflow_name: "Nightly patrol",
    name: "Every five minutes",
    description: null,
    enabled: true,
    schedule_type: "CRON",
    cron_expression: "*/5 * * * *",
    run_at: null,
    timezone: "UTC",
    run_count: 1,
    last_run_at: "2026-01-15T09:55:00Z",
    next_run_at: "2026-01-15T10:05:00Z",
    last_status: "COMPLETED",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("UpcomingSchedules", () => {
  it("shows an empty state when there are no upcoming schedules", () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 5 },
    } as unknown as ReturnType<typeof useSchedules>);

    render(<UpcomingSchedules />);

    expect(screen.getByText("No upcoming schedules.")).toBeInTheDocument();
  });

  it("shows each upcoming schedule's workflow name, time, countdown, and status", () => {
    mockedUseSchedules.mockReturnValue({
      data: { items: [makeSchedule()], total: 1, offset: 0, limit: 5 },
    } as unknown as ReturnType<typeof useSchedules>);

    render(<UpcomingSchedules />);

    expect(screen.getByText("Nightly patrol")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("filters out schedules with no next_run_at", () => {
    mockedUseSchedules.mockReturnValue({
      data: {
        items: [makeSchedule({ id: "sched-2", workflow_name: "No next run", next_run_at: null })],
        total: 1,
        offset: 0,
        limit: 5,
      },
    } as unknown as ReturnType<typeof useSchedules>);

    render(<UpcomingSchedules />);

    expect(screen.getByText("No upcoming schedules.")).toBeInTheDocument();
    expect(screen.queryByText("No next run")).not.toBeInTheDocument();
  });
});
