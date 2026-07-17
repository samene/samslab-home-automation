import Hls from "hls.js";
import { Maximize2, Signal, SignalLow, Square, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCameraStatus } from "@/hooks/useCamera";
import { cn } from "@/lib/utils";
import type { CameraStatusDTO } from "@/types/api";

/**
 * Drives HLS playback ourselves (hls.js) instead of a plain <iframe>/<video
 * src> pointed at MediaMTX's embedded player page. MediaMTX's HLS/WebRTC
 * reads accept neither query-parameter credentials nor a custom header from
 * a passive load — the only way to attach the Authorization header MediaMTX
 * expects for JWT auth is a programmatic HLS client, since Chrome also no
 * longer honors user:pass@host embedded in a URL (removed in 2022). Native
 * Safari HLS (used when hls.js reports unsupported) has no way to carry a
 * custom header either — a known, unavoidable gap for that one browser path.
 */
const _MANIFEST_RETRY_ATTEMPTS = 6;
const _MANIFEST_RETRY_DELAY_MS = 1000;

function useHlsPlayback(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  playbackUrl: string | undefined,
  playbackToken: string | null | undefined,
) {
  const tokenRef = useRef(playbackToken);
  tokenRef.current = playbackToken;

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !playbackUrl) return;

    if (!Hls.isSupported()) {
      video.src = playbackUrl;
      return;
    }

    const hls = new Hls({
      // hls.js's default live-sync distance (3 segments) chases the live
      // edge closely, which is fine on a LAN but leaves little slack for a
      // Pi publishing over a real WAN link: any jitter between MediaMTX
      // muxing a segment and hls.js's playlist refresh noticing it means
      // the player can ask for a segment a beat too early (not written
      // yet) or, after falling behind, one already rotated out of
      // MediaMTX's rolling HLS window — both 404. Trading ~2 more segments
      // of latency for that margin turns an occasional stutter into a
      // steady, if slightly delayed, picture.
      liveSyncDurationCount: 5,
      liveMaxLatencyDurationCount: 10,
      xhrSetup: (xhr) => {
        if (tokenRef.current) {
          xhr.setRequestHeader("Authorization", `Bearer ${tokenRef.current}`);
        }
      },
    });

    let retriesLeft = _MANIFEST_RETRY_ATTEMPTS;
    let retryTimeout: ReturnType<typeof setTimeout> | undefined;

    // A cache-busting param per session, not just per retry: index.m3u8 is
    // otherwise the exact same URL every time "Go Live" is clicked, and its
    // very first fetch legitimately 404s during the startup race below. If
    // that negative response has no explicit no-store header, the browser
    // (or an intermediary) can cache it against that literal URL — so a
    // *second*, genuinely fresh stream session reuses the stale cached 404
    // instead of ever reaching the network, let alone MediaMTX.
    const cacheBustedUrl = `${playbackUrl}${playbackUrl.includes("?") ? "&" : "?"}_t=${Date.now()}`;

    // The dashboard gets playback_url back the instant camera.stream.start
    // is dispatched, but MediaMTX only starts serving index.m3u8 once the
    // agent's RTSP publish (ANNOUNCE/SETUP/RECORD) actually completes a
    // second or two later — the first manifest load routinely 404s in that
    // window. hls.js has no built-in retry for that first load, so without
    // this it fails once, silently, and the video stays blank forever.
    //
    // A failed *manifest* load must be retried via loadSource(), not
    // startLoad(): startLoad()/networkControllers only resume fragment/level
    // loading for a manifest that already parsed successfully — it never
    // re-emits MANIFEST_LOADING, so it does nothing for a manifest that
    // never loaded in the first place (confirmed against hls.js's own
    // source: level-controller.ts only reacts to MANIFEST_LOADING, which
    // only loadSource() ever emits). Calling startLoad() here silently did
    // nothing, which is why retries never actually happened.
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR && retriesLeft > 0) {
        retriesLeft -= 1;
        const isManifestError =
          data.details === Hls.ErrorDetails.MANIFEST_LOAD_ERROR ||
          data.details === Hls.ErrorDetails.MANIFEST_LOAD_TIMEOUT ||
          data.details === Hls.ErrorDetails.MANIFEST_PARSING_ERROR;
        retryTimeout = setTimeout(() => {
          if (isManifestError) {
            hls.loadSource(cacheBustedUrl);
          } else {
            hls.startLoad();
          }
        }, _MANIFEST_RETRY_DELAY_MS);
        return;
      }
      if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        hls.recoverMediaError();
        return;
      }
      hls.destroy();
    });

    hls.loadSource(cacheBustedUrl);
    hls.attachMedia(video);
    void video.play().catch(() => {
      // Autoplay can be blocked until the user interacts with the page; not an error.
    });

    return () => {
      clearTimeout(retryTimeout);
      hls.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- token changes are read via tokenRef, not a dependency
  }, [videoRef, playbackUrl]);
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
}

/** Always present (col 2-3 of the dashboard grid); toggled on/off by its own full-width button. */
export function CameraPanel({
  hasDevice,
  cameraStatus,
  isStarting,
  isStopping,
  onGoLive,
  onStop,
}: CameraPanelProps) {
  const { data: polledStatus, isError } = useCameraStatus({ enabled: cameraStatus?.running === true });
  const videoRef = useRef<HTMLVideoElement>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const status = polledStatus ?? cameraStatus;
  const isActive = status?.running === true;
  const startedAtMs = status?.started_at ? new Date(status.started_at).getTime() : null;

  useHlsPlayback(videoRef, isActive ? status?.playback_url : undefined, status?.playback_token);

  useEffect(() => {
    if (!isActive || !startedAtMs) {
      setElapsedSeconds(0);
      return;
    }
    const tick = () => setElapsedSeconds(Math.max(0, (Date.now() - startedAtMs) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [isActive, startedAtMs]);

  function handleFullscreen() {
    void videoRef.current?.parentElement?.requestFullscreen();
  }

  return (
    <div
      className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-sm"
      data-testid="camera-panel"
    >
      <div className="relative min-h-0 flex-1 bg-black">
        {isActive ? (
          <>
            <video ref={videoRef} title="Live camera stream" autoPlay muted playsInline className="size-full" />
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
            <Button
              type="button"
              variant="secondary"
              size="icon"
              className="absolute top-2 right-2 size-8 rounded-full bg-black/50 text-white hover:bg-black/70"
              onClick={handleFullscreen}
              aria-label="Fullscreen"
            >
              <Maximize2 className="size-4" />
            </Button>
            <div className="absolute right-2 bottom-2 flex items-center gap-1.5 rounded-full bg-black/50 px-2 py-1 text-xs text-white backdrop-blur-sm">
              <span className={cn("inline-flex items-center gap-1", isError && "text-destructive")}>
                {isError ? <SignalLow className="size-3" /> : <Signal className="size-3" />}
              </span>
              {status?.resolution ?? "—"} · {status?.fps ?? "—"}fps
            </div>
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
        className="w-full shrink-0 rounded-none py-5 text-sm font-semibold"
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
    </div>
  );
}
