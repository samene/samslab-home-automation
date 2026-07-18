"""Orchestrates one live camera stream: start, stop, status — nothing else.

Reading frames (OpenCV, via ``FrameSource``) and publishing them (ffmpeg, via
``StreamPublisher``) are both blocking I/O, so the actual frame pump runs on a
background thread, never on the agent's asyncio event loop — command handlers
call into this service through ``asyncio.get_running_loop().run_in_executor``
so a slow camera/publisher never stalls the heartbeat or WebSocket receive
loop. Only one stream is supported at a time; starting while already
streaming or stopping while already stopped are both treated as success, not
an error, matching how a real operator expects a toggle-like control to
behave.
"""

from __future__ import annotations

import hashlib
import importlib.util
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config.settings import AgentSettings
from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.metrics import (
    CAMERA_FRAMES_SENT_TOTAL,
    CAMERA_SNAPSHOT_DURATION_SECONDS,
    CAMERA_SNAPSHOT_FAILURES_TOTAL,
    CAMERA_SNAPSHOT_UPLOAD_DURATION_SECONDS,
    CAMERA_SNAPSHOTS_TOTAL,
    CAMERA_STREAM_ACTIVE,
    CAMERA_STREAM_DURATION_SECONDS,
    CAMERA_STREAM_ERRORS_TOTAL,
    CAMERA_STREAM_START_TOTAL,
    CAMERA_STREAM_STOP_TOTAL,
)
from app.plugins.camera.publisher import FfmpegRtspPublisher, StreamPublisher
from app.plugins.camera.snapshot_uploader import (
    SnapshotUploaderProtocol,
    build_s3_snapshot_uploader,
)
from app.plugins.camera.sources import FrameSource, OpenCvFrameSource, Picamera2FrameSource

_JOIN_TIMEOUT_SECONDS = 5.0
_MEDIAMTX_REACHABLE_TIMEOUT_SECONDS = 0.3


class CameraService:
    """Owns the single active stream's lifecycle and in-memory state."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        frame_source_factory: Callable[[], FrameSource] | None = None,
        publisher_factory: Callable[[], StreamPublisher] | None = None,
        snapshot_frame_source_factory: Callable[[], FrameSource] | None = None,
        uploader: SnapshotUploaderProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._frame_source_factory = frame_source_factory or self._default_frame_source
        self._publisher_factory = publisher_factory or self._default_publisher
        self._snapshot_frame_source_factory = (
            snapshot_frame_source_factory or self._default_snapshot_frame_source
        )
        self._uploader = uploader if uploader is not None else build_s3_snapshot_uploader(settings)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_source: FrameSource | None = None
        self._publisher: StreamPublisher | None = None
        self._started_at: datetime | None = None
        self._frames_sent = 0
        self._last_error: str | None = None

    def _default_frame_source(self) -> FrameSource:
        settings = self._settings
        return self._build_frame_source(width=settings.camera_width, height=settings.camera_height)

    def _default_snapshot_frame_source(self) -> FrameSource:
        settings = self._settings
        return self._build_frame_source(
            width=settings.camera_snapshot_width, height=settings.camera_snapshot_height
        )

    def _build_frame_source(self, *, width: int, height: int) -> FrameSource:
        # A CSI camera module (e.g. Camera Module 3) is only reachable through
        # libcamera/picamera2 on current Raspberry Pi hardware — there is no
        # V4L2 compatibility shim for the Pi 5's SoC, so OpenCV can never open
        # one directly. Prefer picamera2 whenever it's actually installed;
        # fall back to OpenCV for a plain USB/UVC webcam, which V4L2 handles
        # natively.
        settings = self._settings
        if importlib.util.find_spec("picamera2") is not None:
            return Picamera2FrameSource(width=width, height=height, fps=settings.camera_fps)
        return OpenCvFrameSource(
            device_index=settings.camera_device_index,
            width=width,
            height=height,
            fps=settings.camera_fps,
        )

    def _default_publisher(self) -> StreamPublisher:
        return FfmpegRtspPublisher()

    @property
    def last_error(self) -> str | None:
        """The most recent start/streaming failure, or None if nothing has failed."""
        return self._last_error

    @property
    def is_streaming(self) -> bool:
        """Whether the frame-pump thread is currently alive."""
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, publish_token: str | None = None) -> dict[str, Any]:
        """Start streaming, or return the current status if already streaming.

        ``publish_token``, when given, is a MediaMTX JWT with a ``publish``
        permission for this stream — minted server-side and delivered in the
        ``camera.stream.start`` command's payload (see
        ``app/plugins/camera/handlers.py``). Required once a deployment sets
        MediaMTX's ``authMethod: jwt``, since that also covers the RTSP
        publish path; omitted, the static MEDIAMTX_USERNAME/MEDIAMTX_PASSWORD
        settings are used instead (for a MediaMTX instance not using JWT auth
        at all, e.g. local development).
        """
        with self._lock:
            if self.is_streaming:
                return self._status_locked()

            frame_source = self._frame_source_factory()
            publisher = self._publisher_factory()
            try:
                frame_source.open()
                publisher.start(
                    publish_url=self._rtsp_publish_url(publish_token),
                    width=self._settings.camera_width,
                    height=self._settings.camera_height,
                    fps=self._settings.camera_fps,
                    bitrate_kbps=self._settings.camera_bitrate_kbps,
                    preset=self._settings.camera_preset,
                )
            except Exception as error:
                self._last_error = str(error)
                CAMERA_STREAM_ERRORS_TOTAL.inc()
                raise

            self._frame_source = frame_source
            self._publisher = publisher
            self._frames_sent = 0
            self._started_at = datetime.now(UTC)
            self._last_error = None
            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._pump_frames, daemon=True)
            self._thread.start()
            CAMERA_STREAM_ACTIVE.set(1)
            CAMERA_STREAM_START_TOTAL.inc()
            return self._status_locked()

    def _pump_frames(self) -> None:
        """Read-and-publish loop; runs entirely on its own thread.

        However this loop ends — a clean stop, natural end-of-stream, or an
        exception (e.g. the publisher's pipe breaking) — it must release the
        camera/publisher itself, here, rather than leaving that to ``stop()``.
        A stream that dies on its own (nothing called ``stop()``) would
        otherwise leave the hardware camera lock held forever: ``is_streaming``
        correctly flips to ``False`` once this thread exits, but the
        never-released ``Picamera2``/ffmpeg handles keep the camera in
        libcamera's "Running" state, so every subsequent start() attempt
        fails with "Camera in Running state" instead of a fresh, real error.
        """
        frame_source = self._frame_source
        publisher = self._publisher
        assert frame_source is not None
        assert publisher is not None
        try:
            while not self._stop_event.is_set():
                frame = frame_source.read()
                if frame is None:
                    break
                publisher.write(frame)
                self._frames_sent += 1
                CAMERA_FRAMES_SENT_TOTAL.inc()
        except Exception as error:  # pragma: no cover - defensive; surfaced via last_error
            self._last_error = str(error)
            CAMERA_STREAM_ERRORS_TOTAL.inc()
        finally:
            with self._lock:
                publisher.stop()
                frame_source.close()
                self._thread = None
                self._publisher = None
                self._frame_source = None
                self._started_at = None
                CAMERA_STREAM_ACTIVE.set(0)

    def stop(self) -> dict[str, Any]:
        """Stop streaming, or return a zeroed result if not currently streaming."""
        with self._lock:
            if not self.is_streaming:
                return {
                    "duration": 0.0,
                    "frames_sent": 0,
                    "stopped_at": datetime.now(UTC).isoformat(),
                }
            started_at = self._started_at
            self._stop_event.set()
            thread = self._thread

        assert thread is not None
        # Released outside the lock: _pump_frames' own finally block needs it
        # to perform the actual cleanup once this join() lets it proceed.
        thread.join(timeout=_JOIN_TIMEOUT_SECONDS)

        with self._lock:
            duration = (datetime.now(UTC) - started_at).total_seconds() if started_at else 0.0
            frames_sent = self._frames_sent
            stopped_at = datetime.now(UTC)
            CAMERA_STREAM_STOP_TOTAL.inc()
            CAMERA_STREAM_DURATION_SECONDS.observe(duration)
            return {
                "duration": duration,
                "frames_sent": frames_sent,
                "stopped_at": stopped_at.isoformat(),
            }

    def status(self) -> dict[str, Any]:
        """Return the current stream state without changing it."""
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict[str, Any]:
        """Build the status dict; caller must already hold ``self._lock``."""
        running = self.is_streaming
        started_at = self._started_at if running else None
        uptime_seconds = (datetime.now(UTC) - started_at).total_seconds() if started_at else 0.0
        return {
            "running": running,
            "stream_name": self._settings.stream_name,
            "playback_url": self.playback_url(),
            "resolution": f"{self._settings.camera_width}x{self._settings.camera_height}",
            "fps": self._settings.camera_fps,
            "started_at": started_at.isoformat() if started_at else None,
            "uptime_seconds": uptime_seconds,
            "frames_sent": self._frames_sent,
        }

    def capture_snapshot(self) -> dict[str, Any]:
        """Capture one high-resolution still image and upload it to S3.

        Independent of streaming — this can be called whether or not
        ``start()``/``stop()`` has ever run. If a stream is already active,
        this reuses its live ``FrameSource`` (at the stream's *current*
        resolution) without stopping or restarting it. If idle, a *fresh*
        ``FrameSource`` is opened at the higher ``camera_snapshot_width``/
        ``camera_snapshot_height`` resolution — since the point of a
        standalone snapshot is a better-than-streaming-quality still — and
        released again immediately after, so a snapshot never leaves the
        camera open. Raises ``CameraUnavailableError`` if no uploader is
        configured (``AWS_S3_BUCKET``/``AWS_ACCESS_KEY_ID`` unset) or if
        capture/encode/upload fails for any reason. Returns metadata only —
        image bytes never leave this method.

        Reusing the live path's frame source calls its ``read()`` from this
        method's (thread-pool executor) thread while ``_pump_frames`` may
        concurrently be calling the *same* ``read()`` from its own thread.
        This is a deliberate, accepted simplification rather than adding a
        producer/consumer hand-off between the two — the live streaming path
        is explicitly out of scope to modify here, and a single extra
        concurrent grab is, in the worst case, one visually imperceptible
        torn frame for this one snapshot, never a crash or a dropped stream
        frame.
        """
        if self._uploader is None:
            raise CameraUnavailableError(
                "AWS S3 is not configured for snapshot uploads "
                "(AWS_S3_BUCKET/AWS_ACCESS_KEY_ID are unset)"
            )

        capture_started = time.monotonic()
        try:
            frame_bytes, width, height, reused_stream = self._acquire_snapshot_frame()
            if frame_bytes is None:
                raise CameraUnavailableError("Camera returned no frame for snapshot capture")
            original_bytes, thumbnail_bytes = self._encode_snapshot(frame_bytes, width, height)
        except Exception:
            CAMERA_SNAPSHOT_FAILURES_TOTAL.inc()
            raise
        capture_duration = time.monotonic() - capture_started
        CAMERA_SNAPSHOT_DURATION_SECONDS.observe(capture_duration)

        captured_at = datetime.now(UTC)
        sha256_hex = hashlib.sha256(original_bytes).hexdigest()

        self._settings.tmp_directory.mkdir(parents=True, exist_ok=True)
        original_path = self._settings.tmp_directory / f"snapshot-{uuid4()}-original.jpg"
        thumbnail_path = self._settings.tmp_directory / f"snapshot-{uuid4()}-thumbnail.jpg"
        original_path.write_bytes(original_bytes)
        thumbnail_path.write_bytes(thumbnail_bytes)

        upload_started = time.monotonic()
        try:
            result = self._uploader.upload(
                original_bytes=original_bytes,
                thumbnail_bytes=thumbnail_bytes,
                device_name=self._settings.device_name,
                captured_at=captured_at,
            )
        except Exception as error:
            CAMERA_SNAPSHOT_FAILURES_TOTAL.inc()
            raise CameraUnavailableError(f"Failed to upload snapshot to S3: {error}") from error
        finally:
            # Delete temp files whether the upload succeeded or failed — a
            # failed upload leaves nothing durable to retry from in this
            # (deliberately simple, synchronous) design; see docs/agent/CAMERA.md.
            original_path.unlink(missing_ok=True)
            thumbnail_path.unlink(missing_ok=True)
        upload_duration = time.monotonic() - upload_started
        CAMERA_SNAPSHOT_UPLOAD_DURATION_SECONDS.observe(upload_duration)
        CAMERA_SNAPSHOTS_TOTAL.inc()

        return {
            "bucket": result.bucket,
            "filename": result.filename,
            "original_object_key": result.original_object_key,
            "thumbnail_object_key": result.thumbnail_object_key,
            "etag": result.etag,
            "sha256": sha256_hex,
            "width": width,
            "height": height,
            "size": result.size,
            "captured_at": captured_at.isoformat(),
            "reused_stream": reused_stream,
            "capture_duration": capture_duration,
            "upload_duration": upload_duration,
        }

    def _acquire_snapshot_frame(self) -> tuple[bytes | None, int, int, bool]:
        """Grab exactly one raw frame; reuse the live session or open a fresh one.

        Returns ``(frame_bytes, width, height, reused_stream)``. Held under
        ``self._lock`` only long enough to read one frame — the (slower)
        encode/upload work happens outside the lock so it never blocks a
        concurrent ``start()``/``stop()`` call.
        """
        with self._lock:
            if self.is_streaming:
                frame_source = self._frame_source
                assert frame_source is not None
                return (
                    frame_source.read(),
                    self._settings.camera_width,
                    self._settings.camera_height,
                    True,
                )
            frame_source = self._snapshot_frame_source_factory()
            width = self._settings.camera_snapshot_width
            height = self._settings.camera_snapshot_height
            try:
                frame_source.open()
                return frame_source.read(), width, height, False
            finally:
                frame_source.close()

    def _encode_snapshot(self, frame_bytes: bytes, width: int, height: int) -> tuple[bytes, bytes]:
        """Encode a raw BGR24 frame as a full-size JPEG plus a resized thumbnail."""
        import cv2
        import numpy as np

        frame = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height, width, 3))
        ok, original_buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise CameraUnavailableError("Failed to encode snapshot as JPEG")

        thumbnail_width = self._settings.camera_snapshot_thumbnail_width
        thumbnail_height = max(1, round(height * (thumbnail_width / width)))
        thumbnail_frame = cv2.resize(
            frame, (thumbnail_width, thumbnail_height), interpolation=cv2.INTER_AREA
        )
        ok, thumbnail_buffer = cv2.imencode(".jpg", thumbnail_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise CameraUnavailableError("Failed to encode snapshot thumbnail as JPEG")

        return original_buffer.tobytes(), thumbnail_buffer.tobytes()

    def check_camera_detected(self) -> bool:
        """Best-effort check: streaming implies detected; idle falls back to a device-path probe."""
        if self.is_streaming:
            return True
        return Path(f"/dev/video{self._settings.camera_device_index}").exists()

    def check_mediamtx_reachable(self) -> bool:
        """Best-effort, bounded TCP reachability check against the configured RTSP port."""
        try:
            with socket.create_connection(
                (self._settings.mediamtx_host, self._settings.mediamtx_port),
                timeout=_MEDIAMTX_REACHABLE_TIMEOUT_SECONDS,
            ):
                return True
        except OSError:
            return False

    def _rtsp_publish_url(self, publish_token: str | None) -> str:
        """The real, credential-bearing RTSP publish URL — never log this directly.

        When ``publish_token`` is given, it's sent as a ``?token=`` query
        parameter — MediaMTX's actual documented mechanism for handing it a
        JWT over a protocol, like RTSP, that has no request header to attach
        it to (see ``docs/agent/CAMERA.md`` and
        https://mediamtx.org/docs/features/authentication). This is NOT the
        same as RTSP Basic Auth's username/password fields — MediaMTX never
        reads a JWT from there, and doing so instead produces a confusing
        "token is malformed" error from MediaMTX, since it ends up trying to
        parse the base64'd Basic-Auth blob itself as a JWT. Falls back to the
        static MEDIAMTX_USERNAME/MEDIAMTX_PASSWORD settings (real Basic Auth)
        when no token is present, e.g. MediaMTX running ``authMethod: internal``.
        """
        settings = self._settings
        base = f"rtsp://{settings.mediamtx_host}:{settings.mediamtx_port}/{settings.stream_name}"
        if publish_token is not None:
            return f"{base}?token={publish_token}"
        userinfo = f"{settings.mediamtx_username}:{settings.mediamtx_password.get_secret_value()}"
        return f"rtsp://{userinfo}@{settings.mediamtx_host}:{settings.mediamtx_port}/{settings.stream_name}"

    def redacted_publish_url(self) -> str:
        """The RTSP publish URL with credentials stripped, safe to log."""
        settings = self._settings
        return f"rtsp://{settings.mediamtx_host}:{settings.mediamtx_port}/{settings.stream_name}"

    def playback_url(self) -> str:
        """The browser-facing MediaMTX HLS manifest URL, included in command results for logging.

        The browser never fetches this URL directly — the server
        independently constructs its own (see
        ``CameraApplicationService._playback_url``), paired with a
        short-lived MediaMTX JWT the frontend attaches as an Authorization
        header via hls.js, since neither embedding ``user:pass@host``
        credentials nor a plain ``<iframe>``/``<video src>`` load can carry
        auth for MediaMTX's HLS reads. This one exists purely so agent-side
        logs show a real, correctly-shaped URL. No port is appended when
        ``mediamtx_playback_port`` is unset — for a reverse proxy/load
        balancer that terminates the scheme's implicit default port (443 for
        https, 80 for http) and forwards to MediaMTX's real port internally.
        """
        settings = self._settings
        host = settings.mediamtx_host
        if settings.mediamtx_playback_port is not None:
            host = f"{host}:{settings.mediamtx_playback_port}"
        return f"{settings.mediamtx_playback_scheme}://{host}/{settings.stream_name}/index.m3u8"
