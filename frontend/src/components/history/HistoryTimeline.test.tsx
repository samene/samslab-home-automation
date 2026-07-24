import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCancelCommand, useCommand, useDeleteCommand } from "@/hooks/useCommands";
import { useScheduleExecutions } from "@/hooks/useSchedules";
import type { CommandDTO } from "@/types/api";
import { HistoryTimeline } from "./HistoryTimeline";

vi.mock("@/hooks/useCommands");
vi.mock("@/hooks/useSchedules");

const mockedUseCommand = vi.mocked(useCommand);
const mockedUseDeleteCommand = vi.mocked(useDeleteCommand);
const mockedUseCancelCommand = vi.mocked(useCancelCommand);
const mockedUseScheduleExecutions = vi.mocked(useScheduleExecutions);

function makeCommand(overrides: Partial<CommandDTO> = {}): CommandDTO {
  return {
    id: "cmd-1",
    device_id: "device-1",
    command_type: "camera.stream.start",
    status: "COMPLETED",
    priority: "NORMAL",
    payload: {},
    requested_by: null,
    created_at: "2026-01-15T10:00:00Z",
    scheduled_at: null,
    started_at: null,
    completed_at: "2026-01-15T10:00:05Z",
    expires_at: null,
    correlation_id: "corr-1",
    trace_id: null,
    retry_count: 0,
    max_retries: 3,
    ...overrides,
  };
}

function renderTimeline(
  props: Partial<React.ComponentProps<typeof HistoryTimeline>> = {},
) {
  return render(
    <HistoryTimeline
      commands={[makeCommand()]}
      deviceNameById={{ "device-1": "Backyard Pi" }}
      selectionMode={false}
      selectedIds={new Set()}
      onToggleSelect={vi.fn()}
      {...props}
    />,
  );
}

describe("HistoryTimeline", () => {
  beforeEach(() => {
    mockedUseDeleteCommand.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteCommand>);
    mockedUseCancelCommand.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    } as unknown as ReturnType<typeof useCancelCommand>);
    mockedUseScheduleExecutions.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 100 },
    } as unknown as ReturnType<typeof useScheduleExecutions>);
  });

  it("shows an empty state when there is no activity", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    renderTimeline({ commands: [] });
    expect(screen.getByText("No activity found.")).toBeInTheDocument();
  });

  it("labels a command as Manual when no schedule execution matches its correlation_id", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    mockedUseScheduleExecutions.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 100 },
    } as unknown as ReturnType<typeof useScheduleExecutions>);

    renderTimeline();

    expect(screen.getByText("Manual")).toBeInTheDocument();
  });

  it("labels a command as Scheduled via <name> when its correlation_id matches a firing", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    mockedUseScheduleExecutions.mockReturnValue({
      data: {
        items: [
          {
            id: "exec-1",
            schedule_id: "sched-1",
            schedule_name: "Nightly patrol",
            workflow_id: "wf-1",
            workflow_run_id: "corr-1",
            triggered_at: "2026-01-15T09:55:00Z",
            status: "COMPLETED",
            error_message: null,
          },
        ],
        total: 1,
        offset: 0,
        limit: 100,
      },
    } as unknown as ReturnType<typeof useScheduleExecutions>);

    renderTimeline();

    expect(screen.getByText("Scheduled via Nightly patrol")).toBeInTheDocument();
  });

  it("expands a card to reveal duration, result JSON, and error details", async () => {
    mockedUseCommand.mockReturnValue({
      data: {
        ...makeCommand(),
        result: {
          id: "result-1",
          success: false,
          exit_code: 1,
          result: { frames_sent: 42 },
          error_message: "camera not detected",
          duration_ms: 2500,
          completed_at: "2026-01-15T10:00:05Z",
        },
        events: [],
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommand>);

    const user = userEvent.setup();
    renderTimeline();

    await user.click(screen.getByTestId("history-row"));

    expect(await screen.findByText("2.5s")).toBeInTheDocument();
    expect(screen.getByText("camera not detected")).toBeInTheDocument();

    await user.click(screen.getByText("Result (JSON)"));
    expect(screen.getByText(/"frames_sent": 42/)).toBeInTheDocument();
  });

  it("deletes a command after confirming the dialog", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteCommand.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteCommand>);
    mockedUseCommand.mockReturnValue({
      data: { ...makeCommand(), events: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommand>);

    const user = userEvent.setup();
    renderTimeline();

    await user.click(screen.getByTestId("history-row"));
    await user.click(await screen.findByRole("button", { name: /^delete$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete this activity?")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(mutateAsync).toHaveBeenCalledWith("cmd-1");
  });

  it("shows Cancel instead of Delete for a non-terminal command, and cancels it after confirming", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseCancelCommand.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useCancelCommand>);
    mockedUseCommand.mockReturnValue({
      data: { ...makeCommand({ status: "DISPATCHED", completed_at: null }), events: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommand>);

    const user = userEvent.setup();
    renderTimeline({ commands: [makeCommand({ status: "DISPATCHED", completed_at: null })] });

    await user.click(screen.getByTestId("history-row"));
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /^cancel$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Cancel this command?")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^cancel command$/i }));

    expect(mutateAsync).toHaveBeenCalledWith({ commandId: "cmd-1" });
  });

  it("shows no checkbox when selection mode is off", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    renderTimeline({ selectionMode: false });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("shows a checkbox per row in selection mode and calls onToggleSelect", async () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    const onToggleSelect = vi.fn();
    const user = userEvent.setup();
    renderTimeline({ selectionMode: true, onToggleSelect });

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(onToggleSelect).toHaveBeenCalledWith("cmd-1");
  });

  it("reflects an already-selected command as checked", () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    renderTimeline({ selectionMode: true, selectedIds: new Set(["cmd-1"]) });
    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("clicking a checkbox does not also expand the accordion row", async () => {
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);
    const user = userEvent.setup();
    renderTimeline({ selectionMode: true });

    await user.click(screen.getByRole("checkbox"));
    expect(screen.queryByText("Duration")).not.toBeInTheDocument();
  });
});
