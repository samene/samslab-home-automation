"""Where recorded video frames go: writing raw frames to a local, finalized MP4 file.

Mirrors ``publisher.py``'s ``StreamPublisher``/``FfmpegRtspPublisher`` exactly
— the same raw-BGR24-frames-on-stdin ffmpeg subprocess input — but the output
is a local file instead of an RTSP push to MediaMTX: recording never touches
MediaMTX at all. ``-movflags +faststart`` moves the MP4 moov atom to the front
of the file so it's playable via progressive HTTP range requests (e.g. a
presigned S3 GET) without a separate remux pass.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from app.plugins.camera.exceptions import CameraUnavailableError

_STOP_TIMEOUT_SECONDS = 10.0


class Mp4Recorder(Protocol):
    """Something that accepts raw frames and writes them to a local MP4 file."""

    def start(
        self, *, output_path: Path, width: int, height: int, fps: int, bitrate_kbps: int, preset: str
    ) -> None:
        """Begin recording to ``output_path``; raise ``CameraUnavailableError`` on failure."""

    def write(self, frame: bytes) -> None:
        """Write one raw BGR24 frame."""

    def stop(self) -> None:
        """Finalize the MP4 and release any process; safe to call if never started."""


class FfmpegMp4Recorder:
    """Encodes raw frames to a local, finalized MP4 file via a system ``ffmpeg`` subprocess."""

    def __init__(self, *, ffmpeg_path: str = "ffmpeg") -> None:
        self._ffmpeg_path = ffmpeg_path
        self._process: subprocess.Popen[bytes] | None = None

    def start(
        self, *, output_path: Path, width: int, height: int, fps: int, bitrate_kbps: int, preset: str
    ) -> None:
        if shutil.which(self._ffmpeg_path) is None:
            raise CameraUnavailableError(
                f"'{self._ffmpeg_path}' was not found on PATH; ffmpeg is required to record"
            )
        bitrate = f"{bitrate_kbps}k"
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
            "-g",
            str(keyframe_interval),
            # Explicit rate control, same reasoning as FfmpegRtspPublisher's
            # own -b:v/-maxrate/-bufsize: an uncapped CRF encode is fine for a
            # short clip, but a long recording benefits from the same
            # predictable, bounded bitrate a live stream does.
            "-b:v",
            bitrate,
            "-maxrate",
            bitrate,
            "-bufsize",
            f"{bitrate_kbps * 2}k",
            "-f",
            "mp4",
            "-movflags",
            "+faststart",
            "-y",
            str(output_path),
        ]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE)
        except OSError as error:
            raise CameraUnavailableError(f"Could not start ffmpeg: {error}") from error

    def write(self, frame: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            raise CameraUnavailableError("Recorder was not started")
        self._process.stdin.write(frame)

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            if self._process.stdin is not None:
                # Closing stdin (not terminate()) lets ffmpeg see a clean EOF
                # and finish writing the moov atom on its own — sending
                # SIGTERM first, like FfmpegRtspPublisher does for an RTSP
                # push, risks truncating the MP4 mid-finalize. terminate/kill
                # below are only a last-resort fallback if ffmpeg hangs.
                self._process.stdin.close()
            self._process.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except OSError:
            pass
        self._process = None
