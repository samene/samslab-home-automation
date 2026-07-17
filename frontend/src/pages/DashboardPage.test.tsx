import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useCameraStatus, useStartCameraStream, useStopCameraStream } from "@/hooks/useCamera";
import { useCommand, useCommands, useCreateCommand } from "@/hooks/useCommands";
import { usePrimaryDevice } from "@/hooks/useDevices";
import { useDispatcherStatistics, useDispatcherStatus } from "@/hooks/useDispatcher";
import type { CommandDTO, DeviceDTO } from "@/types/api";
import { DashboardPage } from "./DashboardPage";

vi.mock("@/hooks/useDevices");
vi.mock("@/hooks/useCommands");
vi.mock("@/hooks/useCamera");
vi.mock("@/hooks/useDispatcher");
vi.mock("hls.js", () => ({
  default: class {
    static isSupported() {
      return false;
    }
  },
}));

const mockedUsePrimaryDevice = vi.mocked(usePrimaryDevice);
const mockedUseCommands = vi.mocked(useCommands);
const mockedUseCreateCommand = vi.mocked(useCreateCommand);
const mockedUseCommand = vi.mocked(useCommand);
const mockedUseStartCameraStream = vi.mocked(useStartCameraStream);
const mockedUseCameraStatus = vi.mocked(useCameraStatus);
const mockedUseStopCameraStream = vi.mocked(useStopCameraStream);
const mockedUseDispatcherStatus = vi.mocked(useDispatcherStatus);
const mockedUseDispatcherStatistics = vi.mocked(useDispatcherStatistics);

function mockCommonHooks() {
  mockedUseCommand.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
    typeof useCommand
  >);
  mockedUseStartCameraStream.mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useStartCameraStream>);
  mockedUseCameraStatus.mockReturnValue({ data: undefined, isError: false } as unknown as ReturnType<
    typeof useCameraStatus
  >);
  mockedUseStopCameraStream.mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useStopCameraStream>);
  mockedUseDispatcherStatus.mockReturnValue({
    data: undefined,
    isError: true,
  } as unknown as ReturnType<typeof useDispatcherStatus>);
  mockedUseDispatcherStatistics.mockReturnValue({
    data: undefined,
    isError: true,
  } as unknown as ReturnType<typeof useDispatcherStatistics>);
}

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

function makeCommand(overrides: Partial<CommandDTO> = {}): CommandDTO {
  return {
    id: "cmd-1",
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
    correlation_id: "corr-1",
    trace_id: null,
    retry_count: 0,
    max_retries: 3,
    ...overrides,
  };
}

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("DashboardPage", () => {
  it("shows the device's status, heartbeat, and agent version in the hero card", () => {
    mockedUsePrimaryDevice.mockReturnValue({ data: DEVICE, isLoading: false } as unknown as ReturnType<
      typeof usePrimaryDevice
    >);
    mockedUseCommands.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 10 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCreateCommand.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<
      typeof useCreateCommand
    >);
    mockCommonHooks();

    renderDashboard();

    expect(screen.getAllByText("Backyard Pi").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Online").length).toBeGreaterThan(0);
    expect(screen.getByText("1.2.0")).toBeInTheDocument();
    expect(screen.getByText("Camera is idle")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start pump/i })).toBeInTheDocument();
  });

  it("starts the camera stream when Go Live is clicked, and reveals live controls", async () => {
    const startMutateAsync = vi.fn().mockResolvedValue({
      running: true,
      stream_name: "camera",
      playback_url: "http://mediamtx.local:8889/camera/index.m3u8",
      playback_token: "the-jwt",
      resolution: "1280x720",
      fps: 30,
      started_at: "2026-01-15T10:00:00Z",
      uptime_seconds: 0,
      viewer_count: 0,
    });
    mockedUsePrimaryDevice.mockReturnValue({ data: DEVICE, isLoading: false } as unknown as ReturnType<
      typeof usePrimaryDevice
    >);
    mockedUseCommands.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 10 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCreateCommand.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<
      typeof useCreateCommand
    >);
    mockCommonHooks();
    mockedUseStartCameraStream.mockReturnValue({
      mutateAsync: startMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useStartCameraStream>);

    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /go live/i }));

    expect(startMutateAsync).toHaveBeenCalledOnce();
    expect(await screen.findByText("LIVE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop streaming/i })).toBeInTheDocument();
  });

  it("asks for confirmation before sending a pump command, then sends it", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUsePrimaryDevice.mockReturnValue({ data: DEVICE, isLoading: false } as unknown as ReturnType<
      typeof usePrimaryDevice
    >);
    mockedUseCommands.mockReturnValue({
      data: { items: [makeCommand()], total: 1, offset: 0, limit: 10 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCreateCommand.mockReturnValue({ mutateAsync, isPending: false } as unknown as ReturnType<
      typeof useCreateCommand
    >);
    mockCommonHooks();

    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /start pump/i }));
    expect(screen.getByText(/Send "pump.start" to Backyard Pi\?/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(mutateAsync).toHaveBeenCalledWith({ device_id: "device-1", command_type: "pump.start" });
  });

  it("shows an empty state when there is no device", () => {
    mockedUsePrimaryDevice.mockReturnValue({ data: undefined, isLoading: false } as unknown as ReturnType<
      typeof usePrimaryDevice
    >);
    mockedUseCommands.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 10 },
      isLoading: false,
    } as unknown as ReturnType<typeof useCommands>);
    mockedUseCreateCommand.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as unknown as ReturnType<
      typeof useCreateCommand
    >);
    mockCommonHooks();

    renderDashboard();

    expect(screen.getByText("No devices registered yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start pump/i })).toBeDisabled();
  });
});
