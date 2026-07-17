import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCommands } from "@/hooks/useCommands";
import { useDispatcherStatistics, useDispatcherStatus } from "@/hooks/useDispatcher";
import type { CommandDTO, DeviceDTO } from "@/types/api";
import { SystemStatusPanel } from "./SystemStatusPanel";

vi.mock("@/hooks/useDispatcher");
vi.mock("@/hooks/useCommands");

const mockedUseDispatcherStatus = vi.mocked(useDispatcherStatus);
const mockedUseDispatcherStatistics = vi.mocked(useDispatcherStatistics);
const mockedUseCommands = vi.mocked(useCommands);

const DEVICE: DeviceDTO = {
  id: "device-1",
  device_name: "backyard-pi",
  hostname: "backyard-pi.local",
  display_name: "Backyard Pi",
  description: null,
  status: "ONLINE",
  last_seen: new Date().toISOString(),
  agent_version: "1.2.0",
  protocol_version: "1",
  registered_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  enabled: true,
  metadata: {},
  capabilities: [],
};

const COMMAND: CommandDTO = {
  id: "cmd-1",
  device_id: "device-1",
  command_type: "pump.start",
  status: "RUNNING",
  priority: "NORMAL",
  payload: {},
  requested_by: null,
  created_at: "2026-01-15T10:00:00Z",
  scheduled_at: null,
  started_at: "2026-01-15T10:00:01Z",
  completed_at: null,
  expires_at: null,
  correlation_id: "corr-1",
  trace_id: null,
  retry_count: 0,
  max_retries: 3,
};

describe("SystemStatusPanel", () => {
  it("shows a restricted message when the dispatcher endpoints are unavailable (non-admin)", () => {
    mockedUseDispatcherStatus.mockReturnValue({ data: undefined, isError: true } as unknown as ReturnType<
      typeof useDispatcherStatus
    >);
    mockedUseDispatcherStatistics.mockReturnValue({
      data: undefined,
      isError: true,
    } as unknown as ReturnType<typeof useDispatcherStatistics>);
    mockedUseCommands.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useCommands>);

    render(<SystemStatusPanel device={DEVICE} latestCommand={COMMAND} />);

    expect(screen.getByText(/requires an administrator account/i)).toBeInTheDocument();
    expect(screen.getByText("pump.start")).toBeInTheDocument();
  });

  it("shows live dispatcher metrics when available", () => {
    mockedUseDispatcherStatus.mockReturnValue({
      data: {
        running: true,
        started_at: "2026-01-01T00:00:00Z",
        queue_depth: 2,
        pending_ack_count: 1,
        running_count: 1,
        poll_interval_seconds: 1,
      },
      isError: false,
    } as unknown as ReturnType<typeof useDispatcherStatus>);
    mockedUseDispatcherStatistics.mockReturnValue({
      data: {
        commands_dispatched_total: 10,
        dispatch_failures_total: 0,
        dispatcher_retries_total: 0,
        dispatcher_timeouts_total: 0,
        queue_depth: 2,
        pending_ack_count: 1,
        running_count: 1,
      },
      isError: false,
    } as unknown as ReturnType<typeof useDispatcherStatistics>);
    mockedUseCommands.mockReturnValue({ data: { total: 7 } } as unknown as ReturnType<typeof useCommands>);

    render(<SystemStatusPanel device={DEVICE} latestCommand={COMMAND} />);

    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.queryByText(/requires an administrator account/i)).not.toBeInTheDocument();
  });
});
