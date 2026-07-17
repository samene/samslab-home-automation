import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCameraStatus } from "@/hooks/useCamera";
import type { CameraStatusDTO } from "@/types/api";
import { CameraPanel } from "./CameraPanel";

vi.mock("@/hooks/useCamera");

const { isSupportedMock, instances, MockHls } = vi.hoisted(() => {
  class MockHlsInstance {
    handlers: Record<string, (event: string, data: unknown) => void> = {};
    loadSource = vi.fn();
    startLoad = vi.fn();
    attachMedia = vi.fn();
    destroy = vi.fn();
    recoverMediaError = vi.fn();
    on(event: string, handler: (event: string, data: unknown) => void) {
      this.handlers[event] = handler;
    }
  }
  const instances: InstanceType<typeof MockHlsInstance>[] = [];
  const isSupportedMock = vi.fn(() => false);
  class MockHls {
    static isSupported = isSupportedMock;
    static Events = { ERROR: "hlsError" };
    static ErrorTypes = { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" };
    static ErrorDetails = {
      MANIFEST_LOAD_ERROR: "manifestLoadError",
      MANIFEST_LOAD_TIMEOUT: "manifestLoadTimeOut",
      MANIFEST_PARSING_ERROR: "manifestParsingError",
    };
    constructor() {
      const instance = new MockHlsInstance();
      instances.push(instance);
      // eslint-disable-next-line no-constructor-return -- test double standing in for the real class
      return instance;
    }
  }
  return { isSupportedMock, instances, MockHls };
});

vi.mock("hls.js", () => ({ default: MockHls }));

const mockedUseCameraStatus = vi.mocked(useCameraStatus);

function makeStatus(overrides: Partial<CameraStatusDTO> = {}): CameraStatusDTO {
  return {
    running: true,
    stream_name: "backyard-pi",
    playback_url: "https://cams.example.com/backyard-pi/index.m3u8",
    playback_token: "token-123",
    resolution: "1920x1080",
    fps: 30,
    started_at: new Date().toISOString(),
    uptime_seconds: 5,
    viewer_count: 1,
    ...overrides,
  };
}

describe("CameraPanel", () => {
  it("shows an idle state and calls onGoLive when there is no active stream", async () => {
    mockedUseCameraStatus.mockReturnValue({ data: undefined, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);
    const onGoLive = vi.fn();
    const user = userEvent.setup();

    render(
      <CameraPanel
        hasDevice
        cameraStatus={null}
        isStarting={false}
        isStopping={false}
        onGoLive={onGoLive}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByText("Camera is idle")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /go live/i }));
    expect(onGoLive).toHaveBeenCalledOnce();
  });

  it("shows the live video and calls onStop when a stream is active", async () => {
    const status = makeStatus();
    mockedUseCameraStatus.mockReturnValue({ data: status, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);
    const onStop = vi.fn();
    const user = userEvent.setup();

    render(
      <CameraPanel
        hasDevice
        cameraStatus={status}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={onStop}
      />,
    );

    expect(screen.getByText("LIVE")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /stop streaming/i }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("disables the toggle button when there is no device", () => {
    mockedUseCameraStatus.mockReturnValue({ data: undefined, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);

    render(
      <CameraPanel
        hasDevice={false}
        cameraStatus={null}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /go live/i })).toBeDisabled();
  });
});

describe("CameraPanel hls.js manifest-load retry", () => {
  const originalPlay = HTMLMediaElement.prototype.play;

  beforeEach(() => {
    instances.length = 0;
    isSupportedMock.mockReturnValue(true);
    // jsdom doesn't implement play(); the component calls it unconditionally.
    HTMLMediaElement.prototype.play = () => Promise.resolve();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    isSupportedMock.mockReturnValue(false);
    HTMLMediaElement.prototype.play = originalPlay;
  });

  function renderActive() {
    const status = makeStatus();
    mockedUseCameraStatus.mockReturnValue({ data: status, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);
    render(
      <CameraPanel
        hasDevice
        cameraStatus={status}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    const instance = instances[0];
    if (!instance) throw new Error("expected an Hls instance to have been constructed");
    return instance;
  }

  it("retries a fatal manifest load error via loadSource, not startLoad", () => {
    const instance = renderActive();
    expect(instance.loadSource).toHaveBeenCalledTimes(1);

    instance.handlers.hlsError("hlsError", {
      fatal: true,
      type: "networkError",
      details: "manifestLoadError",
    });
    vi.advanceTimersByTime(1000);

    expect(instance.loadSource).toHaveBeenCalledTimes(2);
    expect(instance.startLoad).not.toHaveBeenCalled();
  });

  it("retries a fatal non-manifest network error via startLoad, not loadSource", () => {
    const instance = renderActive();
    expect(instance.loadSource).toHaveBeenCalledTimes(1);

    instance.handlers.hlsError("hlsError", {
      fatal: true,
      type: "networkError",
      details: "fragLoadError",
    });
    vi.advanceTimersByTime(1000);

    expect(instance.startLoad).toHaveBeenCalledTimes(1);
    expect(instance.loadSource).toHaveBeenCalledTimes(1);
  });

  it("ignores a non-fatal error entirely", () => {
    const instance = renderActive();

    instance.handlers.hlsError("hlsError", {
      fatal: false,
      type: "networkError",
      details: "manifestLoadError",
    });
    vi.advanceTimersByTime(1000);

    expect(instance.loadSource).toHaveBeenCalledTimes(1);
    expect(instance.startLoad).not.toHaveBeenCalled();
    expect(instance.destroy).not.toHaveBeenCalled();
  });

  it("recovers a fatal media error via recoverMediaError", () => {
    const instance = renderActive();

    instance.handlers.hlsError("hlsError", { fatal: true, type: "mediaError", details: "bufferStalledError" });

    expect(instance.recoverMediaError).toHaveBeenCalledOnce();
    expect(instance.destroy).not.toHaveBeenCalled();
  });

  it("gives up and destroys on an unrecoverable fatal error", () => {
    const instance = renderActive();

    instance.handlers.hlsError("hlsError", { fatal: true, type: "otherError", details: "internalException" });

    expect(instance.destroy).toHaveBeenCalledOnce();
  });
});
