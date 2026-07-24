import { Camera, Loader2, Maximize2, Signal, SignalLow, Square, TriangleAlert, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCameraStatus } from "@/hooks/useCamera";
import { cn } from "@/lib/utils";
import type { CameraStatusDTO } from "@/types/api";

/**
 * Drives playback via WebRTC (the WHEP protocol) — `playback_url` points at
 * MediaMTX's `/<stream>/whep` endpoint, not an HLS manifest. WHEP's session
 * setup is a normal `fetch()` POST (an SDP offer in, an SDP answer back),
 * not a passive `<video src>` load, so the browser can attach the
 * Authorization header itself directly — no programmatic-vs-native client
 * split, no same-origin proxy, no cookie dance, unlike the HLS approach this
 * replaced. `RTCPeerConnection`/`<video>.srcObject` are uniformly supported
 * across Chrome, Firefox, Edge, Safari desktop, and iOS Safari, so there is
 * exactly one code path here for every browser.
 */
const _WHEP_RETRY_ATTEMPTS = 6;
const _WHEP_RETRY_DELAY_MS = 1000;
const _ICE_GATHERING_TIMEOUT_MS = 2000;
// A public STUN server so a browser behind NAT (the common case — this
// project's whole point is remote viewing) can discover a reflexive ICE
// candidate. MediaMTX may also offer its own via a WHEP response Link
// header; this is a robust default regardless of whether it does.
const _ICE_SERVERS: RTCIceServer[] = [{ urls: "stun:stun.l.google.com:19302" }];

/** Safari-only native fullscreen for a bare `<video>` — no Fullscreen API for arbitrary elements on iOS. */
interface IOSVideoElement extends HTMLVideoElement {
  webkitEnterFullscreen?: () => void;
}
interface WebkitFullscreenElement extends HTMLElement {
  webkitRequestFullscreen?: () => void;
}

function waitForIceGatheringComplete(pc: RTCPeerConnection, timeoutMs: number): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return Promise.race([
    new Promise<void>((resolve) => {
      const onChange = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", onChange);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", onChange);
    }),
    new Promise<void>((resolve) => setTimeout(resolve, timeoutMs)),
  ]);
}

/** Returns whether playback ended up in a state the retry budget couldn't recover from. */
function useWebRtcPlayback(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  playbackUrl: string | undefined,
  playbackToken: string | null | undefined,
): boolean {
  const tokenRef = useRef(playbackToken);
  tokenRef.current = playbackToken;
  const [playbackFailed, setPlaybackFailed] = useState(false);

  useEffect(() => {
    setPlaybackFailed(false);
    const video = videoRef.current;
    if (!video || !playbackUrl) return;
    // Narrowed to a stable local: TS can't carry the `!playbackUrl` guard
    // above into the async `connect()` closure defined below.
    const whepUrl = playbackUrl;
    if (typeof RTCPeerConnection === "undefined") {
      setPlaybackFailed(true);
      return;
    }

    let cancelled = false;
    let retriesLeft = _WHEP_RETRY_ATTEMPTS;
    let retryTimeout: ReturnType<typeof setTimeout> | undefined;
    let pc: RTCPeerConnection | undefined;
    let sessionUrl: string | undefined;

    async function teardown() {
      if (pc) {
        pc.onconnectionstatechange = null;
        pc.ontrack = null;
        pc.close();
        pc = undefined;
      }
      if (sessionUrl) {
        const url = sessionUrl;
        sessionUrl = undefined;
        try {
          await fetch(url, { method: "DELETE" });
        } catch {
          // best-effort — MediaMTX also expires an abandoned WHEP session on its own
        }
      }
    }

    function scheduleRetry() {
      if (cancelled) return;
      if (retriesLeft <= 0) {
        setPlaybackFailed(true);
        return;
      }
      retriesLeft -= 1;
      retryTimeout = setTimeout(() => void connect(), _WHEP_RETRY_DELAY_MS);
    }

    async function connect() {
      await teardown();
      if (cancelled) return;

      const connection = new RTCPeerConnection({ iceServers: _ICE_SERVERS });
      pc = connection;
      // Receive-only: this camera has no microphone (confirmed via
      // MediaMTX's own "1 track (H264)" log), and we are a viewer, never a
      // publisher — the agent's RTSP push to MediaMTX is a separate,
      // unrelated connection this browser code never touches.
      connection.addTransceiver("video", { direction: "recvonly" });
      connection.ontrack = (event) => {
        if (videoRef.current) {
          videoRef.current.srcObject = event.streams[0] ?? new MediaStream([event.track]);
        }
      };
      connection.onconnectionstatechange = () => {
        if (connection.connectionState === "failed") scheduleRetry();
      };

      try {
        const offer = await connection.createOffer();
        await connection.setLocalDescription(offer);
        // Non-trickle ICE: wait for gathering (bounded by a timeout) so the
        // one POST below already carries every candidate found. Simpler and
        // more robust than PATCH-based trickle ICE for a first
        // implementation, at the cost of ~0-2s extra connect latency.
        await waitForIceGatheringComplete(connection, _ICE_GATHERING_TIMEOUT_MS);
        if (cancelled) return;

        const localDescription = connection.localDescription;
        if (!localDescription?.sdp) throw new Error("no local SDP to offer");

        const response = await fetch(whepUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/sdp",
            ...(tokenRef.current ? { Authorization: `Bearer ${tokenRef.current}` } : {}),
          },
          body: localDescription.sdp,
        });
        if (!response.ok) throw new Error(`WHEP offer rejected with ${response.status}`);

        const answerSdp = await response.text();
        const location = response.headers.get("Location");
        sessionUrl = location ? new URL(location, whepUrl).toString() : undefined;

        if (cancelled) return;
        await connection.setRemoteDescription({ type: "answer", sdp: answerSdp });
      } catch {
        if (!cancelled) scheduleRetry();
      }
    }

    void connect();

    return () => {
      cancelled = true;
      clearTimeout(retryTimeout);
      void teardown();
    };
  }, [videoRef, playbackUrl]);

  return playbackFailed;
}

function formatUptime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => value.toString().padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${pad(minutes)}:${pad(secs)}`;
}

interface CameraPanelProps {
  hasDevice: boolean;
  cameraStatus: CameraStatusDTO | null;
  isStarting: boolean;
  isStopping: boolean;
  onGoLive: () => void;
  onStop: () => void;
  onTakeSnapshot: () => void;
  isTakingSnapshot: boolean;
}

/** Always present (col 2-3 of the dashboard grid on desktop; full-width and first on mobile/tablet). */
export function CameraPanel({
  hasDevice,
  cameraStatus,
  isStarting,
  isStopping,
  onGoLive,
  onStop,
  onTakeSnapshot,
  isTakingSnapshot,
}: CameraPanelProps) {
  const { data: polledStatus, isError } = useCameraStatus({ enabled: cameraStatus?.running === true });
  const videoRef = useRef<HTMLVideoElement>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [hasFirstFrame, setHasFirstFrame] = useState(false);

  const status = polledStatus ?? cameraStatus;
  const isActive = status?.running === true;
  const startedAtMs = status?.started_at ? new Date(status.started_at).getTime() : null;

  const playbackFailed = useWebRtcPlayback(
    videoRef,
    isActive ? status?.playback_url : undefined,
    status?.playback_token,
  );

  // Reset whenever a fresh connection attempt starts, so the spinner comes
  // back for a new stream instead of showing stale "connected" chrome from a
  // previous Go Live.
  useEffect(() => {
    setHasFirstFrame(false);
  }, [isActive, status?.playback_url]);

  useEffect(() => {
    if (!isActive || !startedAtMs || !hasFirstFrame) {
      setElapsedSeconds(0);
      return;
    }
    const tick = () => setElapsedSeconds(Math.max(0, (Date.now() - startedAtMs) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [isActive, startedAtMs, hasFirstFrame]);

  function handleFullscreen() {
    const container = videoRef.current?.parentElement as WebkitFullscreenElement | null;
    const video = videoRef.current as IOSVideoElement | null;
    const request = container?.requestFullscreen?.bind(container) ?? container?.webkitRequestFullscreen?.bind(container);
    if (request) {
      Promise.resolve(request())?.catch(() => video?.webkitEnterFullscreen?.());
      return;
    }
    // iOS Safari has no Fullscreen API for a plain <div> — only a <video>
    // element itself supports going fullscreen there.
    video?.webkitEnterFullscreen?.();
  }

  return (
    <div
      className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-sm"
      data-testid="camera-panel"
    >
      <div className="relative min-h-0 flex-1 bg-black">
        {isActive ? (
          <>
            <video
              ref={videoRef}
              title="Live camera stream"
              autoPlay
              muted
              playsInline
              onLoadedData={() => setHasFirstFrame(true)}
              className="size-full object-contain"
            />
            {playbackFailed ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/80 px-4 text-center text-white">
                <TriangleAlert className="size-8 text-warning" />
                <p className="text-sm font-medium">Unable to play the live stream</p>
                <p className="text-xs text-white/70">
                  The stream may still be starting, or your browser couldn't connect. Try Stop
                  Streaming and Go Live again.
                </p>
              </div>
            ) : !hasFirstFrame ? (
              <div
                className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/80 text-white"
                data-testid="camera-connecting"
              >
                <Loader2 className="size-8 animate-spin" />
                <p className="text-sm font-medium">Connecting to camera…</p>
              </div>
            ) : (
              <>
                <div className="absolute top-2 left-2 flex items-center gap-1.5">
                  <Badge className="gap-1.5 rounded-full bg-red-600 px-2 py-0.5 text-white hover:bg-red-600">
                    <span className="relative flex size-1.5">
                      <span className="absolute inline-flex size-full animate-ping rounded-full bg-white/80" />
                      <span className="relative inline-flex size-1.5 rounded-full bg-white" />
                    </span>
                    LIVE
                  </Badge>
                  <Badge variant="secondary" className="rounded-full bg-black/50 text-xs text-white backdrop-blur-sm">
                    {formatUptime(elapsedSeconds)}
                  </Badge>
                </div>
                <div className="absolute right-2 bottom-2 flex items-center gap-1.5 rounded-full bg-black/50 px-2 py-1 text-xs text-white backdrop-blur-sm">
                  <span className={cn("inline-flex items-center gap-1", isError && "text-destructive")}>
                    {isError ? <SignalLow className="size-3" /> : <Signal className="size-3" />}
                  </span>
                  {status?.resolution ?? "—"} · {status?.fps ?? "—"}fps
                </div>
              </>
            )}
            <Button
              type="button"
              variant="secondary"
              size="icon"
              className="absolute top-2 right-2 size-10 rounded-full bg-black/50 text-white hover:bg-black/70 coarse:size-11"
              onClick={handleFullscreen}
              aria-label="Fullscreen"
            >
              <Maximize2 className="size-4" />
            </Button>
          </>
        ) : (
          <div className="flex size-full flex-col items-center justify-center gap-2 text-muted-foreground">
            <Video className="size-8" />
            <p className="text-sm">Camera is idle</p>
          </div>
        )}
      </div>

      <Button
        type="button"
        size="lg"
        variant={isActive ? "destructive" : "default"}
        className="w-full shrink-0 rounded-none py-5 text-sm font-semibold coarse:py-6"
        disabled={!hasDevice || isStarting || isStopping}
        onClick={isActive ? onStop : onGoLive}
      >
        {isActive ? (
          <>
            <Square className="size-4" />
            {isStopping ? "Stopping…" : "Stop Streaming"}
          </>
        ) : (
          <>
            <Video className="size-4" />
            {isStarting ? "Starting live camera…" : "Go Live"}
          </>
        )}
      </Button>

      {isActive ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-full shrink-0 rounded-none border-0 border-t border-border py-4 text-xs font-medium coarse:py-5"
          disabled={isTakingSnapshot}
          onClick={onTakeSnapshot}
        >
          <Camera className="size-3.5" />
          {isTakingSnapshot ? "Capturing…" : "Take Snapshot"}
        </Button>
      ) : null}
    </div>
  );
}
