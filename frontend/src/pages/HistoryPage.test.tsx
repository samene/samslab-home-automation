import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useBulkDeleteCommands,
  useCancelCommand,
  useCommand,
  useCommands,
  useDeleteCommand,
} from "@/hooks/useCommands";
import { useDevices } from "@/hooks/useDevices";
import { useScheduleExecutions } from "@/hooks/useSchedules";
import type { CommandDTO, DevicePageDTO } from "@/types/api";
import { HistoryPage } from "./HistoryPage";

vi.mock("@/hooks/useDevices");
vi.mock("@/hooks/useCommands");
vi.mock("@/hooks/useSchedules");

const mockedUseDevices = vi.mocked(useDevices);
const mockedUseCommands = vi.mocked(useCommands);
const mockedUseCommand = vi.mocked(useCommand);
const mockedUseDeleteCommand = vi.mocked(useDeleteCommand);
const mockedUseCancelCommand = vi.mocked(useCancelCommand);
const mockedUseBulkDeleteCommands = vi.mocked(useBulkDeleteCommands);
const mockedUseScheduleExecutions = vi.mocked(useScheduleExecutions);

const DEVICES: DevicePageDTO = {
  items: [
    {
      id: "device-1",
      device_name: "backyard-pi",
      hostname: "backyard-pi.local",
      display_name: "Backyard Pi",
      description: null,
      status: "ONLINE",
      last_seen: null,
      agent_version: null,
      protocol_version: null,
      registered_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      enabled: true,
      metadata: {},
      capabilities: [],
    },
  ],
  total: 1,
  offset: 0,
  limit: 100,
};

function makeCommands(total: number): CommandDTO[] {
  return Array.from({ length: total }, (_, index) => ({
    id: `cmd-${index}`,
    device_id: "device-1",
    command_type: "pump.start",
    status: "COMPLETED",
    priority: "NORMAL",
    payload: {},
    requested_by: null,
    created_at: "2026-01-15T10:00:00Z",
    scheduled_at: null,
    started_at: null,
    completed_at: "2026-01-15T10:00:05Z",
    expires_at: null,
    correlation_id: `corr-${index}`,
    trace_id: null,
    retry_count: 0,
    max_retries: 3,
  }));
}

describe("HistoryPage", () => {
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
    mockedUseBulkDeleteCommands.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({ total: 0, failed: 0 }),
      isPending: false,
    } as unknown as ReturnType<typeof useBulkDeleteCommands>);
  });

  it("renders activity cards and disables pagination when everything fits on one page", () => {
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
    mockedUseCommands.mockReturnValue({
      data: { items: makeCommands(3), total: 3, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);

    render(<HistoryPage />);

    expect(screen.getAllByTestId("history-row")).toHaveLength(3);
    expect(screen.getAllByText("Backyard Pi").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("enables Next when there are more pages, and expands a card's details on click", async () => {
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
    mockedUseCommands.mockReturnValue({
      data: { items: makeCommands(50), total: 75, offset: 0, limit: 50 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<
      typeof useCommand
    >);

    const user = userEvent.setup();
    render(<HistoryPage />);

    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getAllByTestId("history-row")[0]);
    expect(mockedUseCommand).toHaveBeenCalledWith("cmd-0");
  });

  it("filters the visible cards by the search box", async () => {
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
    mockedUseCommands.mockReturnValue({
      data: {
        items: [
          { ...makeCommands(1)[0], id: "cmd-pump", command_type: "pump.start" },
          { ...makeCommands(1)[0], id: "cmd-camera", command_type: "camera.stream.start" },
        ],
        total: 2,
        offset: 0,
        limit: 20,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);

    const user = userEvent.setup();
    render(<HistoryPage />);

    expect(screen.getAllByTestId("history-row")).toHaveLength(2);

    await user.type(screen.getByPlaceholderText(/search/i), "camera");

    expect(screen.getAllByTestId("history-row")).toHaveLength(1);
    expect(screen.getByText("camera.stream.start")).toBeInTheDocument();
  });

  it("enters selection mode, selects commands individually, and bulk deletes them", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ total: 2, failed: 0 });
    mockedUseBulkDeleteCommands.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useBulkDeleteCommands>);
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
    mockedUseCommands.mockReturnValue({
      data: { items: makeCommands(3), total: 3, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);

    const user = userEvent.setup();
    render(<HistoryPage />);

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /select/i }));

    const checkboxes = screen.getAllByRole("checkbox");
    // First checkbox is "Select all"; the rest are per-row.
    expect(checkboxes).toHaveLength(4);
    await user.click(checkboxes[1]);
    await user.click(checkboxes[2]);

    expect(screen.getByText("(2 selected)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /delete \(2\)/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete 2 commands?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(mutateAsync).toHaveBeenCalledWith(["cmd-0", "cmd-1"]);
  });

  it("select all selects every visible row, and cancel exits selection mode", async () => {
    mockedUseDevices.mockReturnValue({ data: DEVICES } as unknown as ReturnType<typeof useDevices>);
    mockedUseCommands.mockReturnValue({
      data: { items: makeCommands(3), total: 3, offset: 0, limit: 20 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof useCommand
    >);

    const user = userEvent.setup();
    render(<HistoryPage />);

    await user.click(screen.getByRole("button", { name: /select/i }));
    await user.click(screen.getByLabelText(/select all/i));

    expect(screen.getByText("(3 selected)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
