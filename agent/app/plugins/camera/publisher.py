"""Where video frames go: publishing raw frames to MediaMTX as an H.264 RTSP stream.

OpenCV's ``VideoCapture`` reads frames; it has no built-in RTSP *publish*
sink, so ``FfmpegRtspPublisher`` shells out to the system ``ffmpeg`` binary,
feeding it raw BGR24 frames on stdin and letting it do the H.264 encode + RTSP
push to MediaMTX. This is the one place a system binary (not a Python
dependency) is required — see ``docs/agent/CAMERA.md`` for the prerequisite.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from app.plugins.camera.exceptions import CameraUnavailableError

_STOP_TIMEOUT_SECONDS = 5.0


class StreamPublisher(Protocol):
    """Something that accepts raw frames and pushes them out as a live stream."""

    def start(
        self, *, publish_url: str, width: int, height: int, fps: int, bitrate_kbps: int, preset: str
    ) -> None:
        """Begin publishing; raise ``CameraUnavailableError`` on failure."""

    def write(self, frame: bytes) -> None:
        """Publish one raw BGR24 frame."""

    def stop(self) -> None:
        """Stop publishing and release any process/connection; safe to call if never started."""


class FfmpegRtspPublisher:
    """Pushes raw frames to an RTSP URL as H.264 via a system ``ffmpeg`` subprocess."""

    def __init__(self, *, ffmpeg_path: str = "ffmpeg") -> None:
        self._ffmpeg_path = ffmpeg_path
        self._process: subprocess.Popen[bytes] | None = None

    def start(
        self, *, publish_url: str, width: int, height: int, fps: int, bitrate_kbps: int, preset: str
    ) -> None:
        if shutil.which(self._ffmpeg_path) is None:
            raise CameraUnavailableError(
                f"'{self._ffmpeg_path}' was not found on PATH; ffmpeg is required to publish"
            )
        bitrate = f"{bitrate_kbps}k"
        # A keyframe roughly every 2 seconds: cheap insurance against a long,
        # possibly lossy WAN path — a viewer that joins mid-stream, or a
        # decoder that drops a frame, only ever waits up to ~2s to recover a
        # clean picture, at a small, constant bitrate cost.
        keyframe_interval = max(1, fps * 2)
        command = [
            self._ffmpeg_path,
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-tune",
            "zerolatency",
            "-g",
            str(keyframe_interval),
            # Explicit rate control: without -b:v, libx264 falls back to CRF
            # (quality-targeted, variable bitrate) — fine on a local network,
            # but on a long, bandwidth-constrained WAN link (e.g. Pi in India
            # publishing to a server in Europe) an uncapped variable bitrate
            # can burst above what the path actually sustains, causing
            # buffering/stalls that look far worse than steady, moderate
            # quality. -maxrate pinned to the same value as -b:v makes this
            # an effectively-constant bitrate; -bufsize (2x the target) is
            # the VBV window that smooths short bursts without letting them
            # run away.
            "-b:v",
            bitrate,
            "-maxrate",
            bitrate,
            "-bufsize",
            f"{bitrate_kbps * 2}k",
            "-f",
            "rtsp",
            # Without this, ffmpeg defaults to UDP for the actual RTP data
            # while only the RTSP control channel is TCP — the handshake and
            # initial "publishing" succeed either way, but across any
            # network path where UDP isn't reliably reaching the server
            # (NAT, a firewall, or just the public internet), no video data
            # actually arrives; MediaMTX then times out the session as idle
            # a few seconds in, and ffmpeg's next write gets a broken pipe.
            # Forcing RTP-over-TCP-interleaved avoids needing a second,
            # separate data path at all.
            "-rtsp_transport",
            "tcp",
            publish_url,
        ]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE)
        except OSError as error:
            raise CameraUnavailableError(f"Could not start ffmpeg: {error}") from error

    def write(self, frame: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            raise CameraUnavailableError("Publisher was not started")
        self._process.stdin.write(frame)

    def stop(self) -> None:
        if self._process is None:
            return
        # Best-effort: the pipe may already be broken (e.g. ffmpeg exited on
        # its own after a muxer error) — that must not prevent releasing our
        # own reference below, which CameraService's cleanup path depends on
        # completing unconditionally.
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
            self._process.terminate()
            try:
                self._process.wait(timeout=_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except OSError:
            pass
        self._process = None
