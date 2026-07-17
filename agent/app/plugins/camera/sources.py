"""Where video frames come from.

``FrameSource`` is the seam ``CameraService`` depends on — real hardware
access (``OpenCvFrameSource`` or ``Picamera2FrameSource``) lives only behind
this protocol, never imported by ``CameraService`` or a command handler
directly. Tests inject a fake implementation instead of touching real camera
hardware (see ``app/tests/test_camera_service.py``).

Raspberry Pi 5 (and 4/3 on current Raspberry Pi OS) exposes its camera only
through ``libcamera`` — there is no V4L2 compatibility shim for the Pi 5's
SoC, so ``OpenCvFrameSource`` can never open a CSI camera module (a USB UVC
webcam is a different story; that still works fine through OpenCV/V4L2).
``Picamera2FrameSource`` is the real backend for a CSI camera module (e.g.
Camera Module 3); ``CameraService`` picks whichever is importable, preferring
Picamera2 when both are present.
"""

from __future__ import annotations

import contextlib
from typing import Protocol

from app.plugins.camera.exceptions import CameraUnavailableError


class FrameSource(Protocol):
    """Something that can be opened, read frame-by-frame, and closed."""

    def open(self) -> None:
        """Open the underlying device; raise ``CameraUnavailableError`` on failure."""

    def read(self) -> bytes | None:
        """Return one raw BGR24 frame, or ``None`` once no more frames are available."""

    def close(self) -> None:
        """Release the underlying device; safe to call even if never opened."""


class OpenCvFrameSource:
    """Reads frames from a local camera device via OpenCV's ``VideoCapture``.

    Uses whatever backend OpenCV picks for the platform (V4L2 on Linux, which
    is what the Raspberry Pi camera stack exposes) — no GStreamer/Picamera2
    pipeline is hand-built here. Swapping in a ``Picamera2``-backed
    ``FrameSource`` later needs no change to ``CameraService``, only a new
    class satisfying this same protocol.
    """

    def __init__(self, *, device_index: int, width: int, height: int, fps: int) -> None:
        self._device_index = device_index
        self._width = width
        self._height = height
        self._fps = fps
        self._capture: object | None = None

    def open(self) -> None:
        try:
            import cv2
        except ImportError as error:
            raise CameraUnavailableError(
                "opencv-python is not installed; install the 'camera' extra"
            ) from error

        capture = cv2.VideoCapture(self._device_index)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        capture.set(cv2.CAP_PROP_FPS, self._fps)
        if not capture.isOpened():
            capture.release()
            raise CameraUnavailableError(f"Could not open camera device index {self._device_index}")
        self._capture = capture

    def read(self) -> bytes | None:
        if self._capture is None:
            return None
        ok, frame = self._capture.read()  # type: ignore[attr-defined]
        if not ok:
            return None
        result: bytes = frame.tobytes()
        return result

    def close(self) -> None:
        if self._capture is None:
            return
        with contextlib.suppress(Exception):
            self._capture.release()  # type: ignore[attr-defined]
        self._capture = None


class Picamera2FrameSource:
    """Reads frames from a CSI camera module (e.g. Camera Module 3) via ``picamera2``.

    ``picamera2`` wraps ``libcamera`` — the only camera stack Raspberry Pi OS
    exposes for a CSI module on current hardware (Pi 5 included). It is not a
    plain ``pip install``-able package on its own: the actual ``libcamera``
    Python bindings only come from the OS's own build
    (``sudo apt install python3-picamera2``), so the agent's venv must be
    created with ``--system-site-packages`` to see them — see
    ``docs/agent/CAMERA.md``.
    """

    def __init__(self, *, width: int, height: int, fps: int) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._picam2: object | None = None

    def open(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as error:
            raise CameraUnavailableError(
                "picamera2 is not installed; run 'sudo apt install python3-picamera2' "
                "and recreate this agent's venv with --system-site-packages"
            ) from error

        picam2 = Picamera2()
        # "BGR888" matches ffmpeg's configured "-pix_fmt bgr24" input; if
        # captured colors look swapped on your camera, try "RGB888" instead —
        # picamera2's format naming is a known source of confusion.
        config = picam2.create_video_configuration(
            main={"size": (self._width, self._height), "format": "BGR888"},
            controls={"FrameRate": self._fps},
        )
        picam2.configure(config)
        try:
            picam2.start()
        except Exception as error:
            raise CameraUnavailableError(f"Could not start Picamera2: {error}") from error
        self._picam2 = picam2

    def read(self) -> bytes | None:
        if self._picam2 is None:
            return None
        array = self._picam2.capture_array()  # type: ignore[attr-defined]
        result: bytes = array.tobytes()
        return result

    def close(self) -> None:
        if self._picam2 is None:
            return
        # picamera2 runs its own internal background thread delivering
        # completed-request callbacks; that thread can still be mid-callback
        # when stop()/close() run, which has been observed to raise inside
        # picamera2 itself (e.g. AttributeError on a half-torn-down object).
        # Best-effort both calls independently so a picamera2-internal race
        # can never prevent releasing our own reference — if it did, the
        # camera would stay stuck in libcamera's "Running" state and every
        # future start() would fail with "Camera in Running state" instead
        # of a fresh, real error.
        with contextlib.suppress(Exception):
            self._picam2.stop()  # type: ignore[attr-defined]
        with contextlib.suppress(Exception):
            self._picam2.close()  # type: ignore[attr-defined]
        self._picam2 = None
