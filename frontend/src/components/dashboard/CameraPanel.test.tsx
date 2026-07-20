import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCameraStatus } from "@/hooks/useCamera";
import type { CameraStatusDTO } from "@/types/api";
import { CameraPanel } from "./CameraPanel";

vi.mock("@/hooks/useCamera");

const { instances, MockRTCPeerConnection } = vi.hoisted(() => {
  class MockPeerConnection {
    localDescription: { type: string; sdp: string } | null = null;
    iceGatheringState: "new" | "gathering" | "complete" = "new";
    connectionState: "new" | "connecting" | "connected" | "disconnected" | "failed" | "closed" = "new";
    ontrack: ((event: { streams: MediaStream[] }) => void) | null = null;
    onconnectionstatechange: (() => void) | null = null;
    private listeners: Record<string, Array<() => void>> = {};
    addTransceiver = vi.fn();
    close = vi.fn();
    createOffer = vi.fn(async () => ({ type: "offer", sdp: "mock-offer-sdp" }));
    setRemoteDescription = vi.fn(async () => {});
    setLocalDescription = vi.fn(async (desc: { type: string; sdp: string }) => {
      this.localDescription = desc;
    });
    addEventListener(event: string, handler: () => void) {
      (this.listeners[event] ??= []).push(handler);
    }
    removeEventListener(event: string, handler: () => void) {
      this.listeners[event] = (this.listeners[event] ?? []).filter((h) => h !== handler);
    }
    completeIceGathering() {
      this.iceGatheringState = "complete";
      this.listeners.icegatheringstatechange?.forEach((h) => h());
    }
    simulateTrack(stream: MediaStream) {
      this.ontrack?.({ streams: [stream] });
    }
    simulateConnectionStateChange(state: MockPeerConnection["connectionState"]) {
      this.connectionState = state;
      this.onconnectionstatechange?.();
    }
    constructor() {
      instances.push(this);
    }
  }
  const instances: MockPeerConnection[] = [];
  return { instances, MockRTCPeerConnection: MockPeerConnection };
});

const mockedUseCameraStatus = vi.mocked(useCameraStatus);

function makeStatus(overrides: Partial<CameraStatusDTO> = {}): CameraStatusDTO {
  return {
    running: true,
    stream_name: "backyard-pi",
    playback_url: "https://cams.example.com/backyard-pi/whep",
    playback_token: "token-123",
    resolution: "1920x1080",
    fps: 30,
    started_at: new Date().toISOString(),
    uptime_seconds: 5,
    viewer_count: 1,
    ...overrides,
  };
}

function renderActive(overrides: Partial<CameraStatusDTO> = {}) {
  const status = makeStatus(overrides);
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
      onTakeSnapshot={vi.fn()}
      isTakingSnapshot={false}
    />,
  );
  return status;
}

/** Waits for the Nth (0-indexed) RTCPeerConnection to reach the point where it's ready
 * for the ICE-gathering wait to be resolved, then resolves it. */
async function driveConnectAttempt(index: number) {
  // A generous timeout: attempt N>0 only appears after the real 1s retry
  // delay elapses, which is close enough to vi.waitFor's ~1s default to be
  // a flaky race without headroom.
  await vi.waitFor(() => expect(instances.length).toBeGreaterThan(index), { timeout: 3000 });
  await vi.waitFor(() => expect(instances[index].setLocalDescription).toHaveBeenCalled(), { timeout: 3000 });
  instances[index].completeIceGathering();
}

describe("CameraPanel", () => {
  beforeEach(() => {
    instances.length = 0;
    vi.stubGlobal("RTCPeerConnection", MockRTCPeerConnection);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 500 })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

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
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot={false}
      />,
    );

    expect(screen.getByText("Camera is idle")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /go live/i }));
    expect(onGoLive).toHaveBeenCalledOnce();
  });

  it("hides the Take Snapshot button when there is no active stream", () => {
    mockedUseCameraStatus.mockReturnValue({ data: undefined, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);

    render(
      <CameraPanel
        hasDevice
        cameraStatus={null}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={vi.fn()}
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot={false}
      />,
    );

    expect(screen.queryByRole("button", { name: /take snapshot/i })).not.toBeInTheDocument();
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
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot={false}
      />,
    );

    expect(screen.getByText("LIVE")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /stop streaming/i }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("shows the Take Snapshot button while the stream is active, and it calls onTakeSnapshot", async () => {
    const status = makeStatus();
    mockedUseCameraStatus.mockReturnValue({ data: status, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);
    const onTakeSnapshot = vi.fn();
    const user = userEvent.setup();

    render(
      <CameraPanel
        hasDevice
        cameraStatus={status}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={vi.fn()}
        onTakeSnapshot={onTakeSnapshot}
        isTakingSnapshot={false}
      />,
    );

    const button = screen.getByRole("button", { name: /take snapshot/i });
    await user.click(button);
    expect(onTakeSnapshot).toHaveBeenCalledOnce();
  });

  it("disables the Take Snapshot button and shows Capturing… while taking a snapshot", () => {
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
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot
      />,
    );

    expect(screen.getByRole("button", { name: /capturing/i })).toBeDisabled();
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
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot={false}
      />,
    );

    expect(screen.getByRole("button", { name: /go live/i })).toBeDisabled();
  });
});

describe("CameraPanel WHEP playback", () => {
  beforeEach(() => {
    instances.length = 0;
    vi.stubGlobal("RTCPeerConnection", MockRTCPeerConnection);
    // jsdom doesn't implement MediaStream either — only needed as an opaque
    // reference-equality token here, no real media behavior required.
    vi.stubGlobal(
      "MediaStream",
      class {
        constructor(_tracks?: unknown[]) {}
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the received track on the video element once negotiation completes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("mock-answer-sdp", { status: 201, headers: { Location: "/whep/session123" } }),
      ),
    );
    const fakeStream = new MediaStream();

    renderActive();
    await driveConnectAttempt(0);
    await vi.waitFor(() => expect(instances[0].setRemoteDescription).toHaveBeenCalled());
    instances[0].simulateTrack(fakeStream);

    const video = document.querySelector("video") as HTMLVideoElement;
    expect(video.srcObject).toBe(fakeStream);
  });

  it("POSTs the SDP offer with the Authorization header and application/sdp content type", async () => {
    const fetchMock = vi.fn(
      async () => new Response("mock-answer-sdp", { status: 201, headers: { Location: "/whep/session123" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const status = renderActive();
    await driveConnectAttempt(0);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(fetchMock).toHaveBeenCalledWith(status.playback_url, {
      method: "POST",
      headers: { "Content-Type": "application/sdp", Authorization: `Bearer ${status.playback_token}` },
      body: "mock-offer-sdp",
    });
  });

  it("closes the peer connection and DELETEs the WHEP session when the stream stops", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") return new Response("", { status: 200 });
      return new Response("mock-answer-sdp", {
        status: 201,
        headers: { Location: "https://cams.example.com/whep/session123" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const status = makeStatus();
    mockedUseCameraStatus.mockReturnValue({ data: status, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);

    const { rerender } = render(
      <CameraPanel
        hasDevice
        cameraStatus={status}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={vi.fn()}
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot={false}
      />,
    );
    await driveConnectAttempt(0);
    await vi.waitFor(() => expect(instances[0].setRemoteDescription).toHaveBeenCalled());

    // Mirrors what the real DashboardPage does after Stop Streaming succeeds:
    // cameraStatus flips to null, unmounting the effect that drove connect().
    mockedUseCameraStatus.mockReturnValue({ data: undefined, isError: false } as unknown as ReturnType<
      typeof useCameraStatus
    >);
    rerender(
      <CameraPanel
        hasDevice
        cameraStatus={null}
        isStarting={false}
        isStopping={false}
        onGoLive={vi.fn()}
        onStop={vi.fn()}
        onTakeSnapshot={vi.fn()}
        isTakingSnapshot={false}
      />,
    );

    await vi.waitFor(() => expect(instances[0].close).toHaveBeenCalledOnce());
    await vi.waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("https://cams.example.com/whep/session123", { method: "DELETE" }),
    );
  });

  it("retries with a fresh RTCPeerConnection after an initial failure, then succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockResolvedValueOnce(
        new Response("mock-answer-sdp", { status: 201, headers: { Location: "/whep/session123" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderActive();
    await driveConnectAttempt(0);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    // Real 1s retry delay — deliberately not using fake timers here, since
    // the connect() flow is a genuine multi-step async chain (createOffer /
    // setLocalDescription / ICE gathering / fetch) that fake timers would
    // need careful manual interleaving to drive correctly; a real, bounded
    // wait is simpler and less fragile for a mock this shaped.
    await driveConnectAttempt(1);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 3000 });
    await vi.waitFor(() => expect(instances[1].setRemoteDescription).toHaveBeenCalled());
  }, 8000);

  it("reconnects when an established connection's state becomes failed", async () => {
    const fetchMock = vi.fn(
      async () => new Response("mock-answer-sdp", { status: 201, headers: { Location: "/whep/session123" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderActive();
    await driveConnectAttempt(0);
    await vi.waitFor(() => expect(instances[0].setRemoteDescription).toHaveBeenCalled());

    instances[0].simulateConnectionStateChange("failed");

    await vi.waitFor(() => expect(instances).toHaveLength(2), { timeout: 3000 });
    expect(instances[0].close).toHaveBeenCalled();
  }, 5000);

  it("shows the error state after exhausting all retries", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 404 })));

    renderActive();
    for (let attempt = 0; attempt <= 6; attempt++) {
      await driveConnectAttempt(attempt);
    }

    await vi.waitFor(() => expect(screen.getByText("Unable to play the live stream")).toBeInTheDocument(), {
      timeout: 3000,
    });
  }, 15000);
});
