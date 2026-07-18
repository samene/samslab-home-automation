import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as cameraApi from "@/lib/api/camera";
import type { CameraSnapshotDTO, CameraStatusDTO, CameraStopDTO } from "@/types/api";
import { useCameraStatus, useStartCameraStream, useStopCameraStream, useTakeSnapshot } from "./useCamera";

vi.mock("@/lib/api/camera");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const STATUS: CameraStatusDTO = {
  running: true,
  stream_name: "camera",
  playback_url: "http://mediamtx.local:8889/camera/index.m3u8",
  playback_token: "the-jwt",
  resolution: "1280x720",
  fps: 30,
  started_at: "2026-01-15T10:00:00Z",
  uptime_seconds: 0,
  viewer_count: 0,
};

const STOP_RESULT: CameraStopDTO = {
  status: "stopped",
  duration_seconds: 12.5,
  frames_sent: 375,
  stopped_at: "2026-01-15T10:05:00Z",
};

const SNAPSHOT: CameraSnapshotDTO = {
  id: "snap-1",
  device_id: "device-1",
  command_id: "cmd-1",
  filename: "snap-1.jpg",
  width: 1920,
  height: 1080,
  size: 204800,
  captured_at: "2026-01-15T10:00:00Z",
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useCameraStatus", () => {
  it("fetches the camera status", async () => {
    vi.mocked(cameraApi.getCameraStatus).mockResolvedValue(STATUS);
    const { result } = renderHook(() => useCameraStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(STATUS);
  });

  it("does not fetch when disabled", () => {
    const { result } = renderHook(() => useCameraStatus({ enabled: false }), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(cameraApi.getCameraStatus).not.toHaveBeenCalled();
  });
});

describe("useStartCameraStream", () => {
  it("starts the stream and shows a success toast", async () => {
    vi.mocked(cameraApi.startCameraStream).mockResolvedValue(STATUS);
    const { result } = renderHook(() => useStartCameraStream(), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Camera stream started");
  });

  it("shows an error toast when starting fails", async () => {
    vi.mocked(cameraApi.startCameraStream).mockRejectedValue(new Error("no device"));
    const { result } = renderHook(() => useStartCameraStream(), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("no device");
  });
});

describe("useStopCameraStream", () => {
  it("stops the stream and shows a success toast", async () => {
    vi.mocked(cameraApi.stopCameraStream).mockResolvedValue(STOP_RESULT);
    const { result } = renderHook(() => useStopCameraStream(), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Camera stream stopped");
  });
});

describe("useTakeSnapshot", () => {
  it("captures a snapshot and shows a success toast", async () => {
    vi.mocked(cameraApi.takeSnapshot).mockResolvedValue(SNAPSHOT);
    const { result } = renderHook(() => useTakeSnapshot(), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("Snapshot captured");
  });

  it("shows an error toast when capturing fails", async () => {
    vi.mocked(cameraApi.takeSnapshot).mockRejectedValue(new Error("camera busy"));
    const { result } = renderHook(() => useTakeSnapshot(), { wrapper });

    result.current.mutate();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith("camera busy");
  });
});
