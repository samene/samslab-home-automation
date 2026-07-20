"""Tests for CameraService: start/stop/status, idempotency, and failure handling.

Uses fake FrameSource/StreamPublisher implementations rather than real
OpenCV/ffmpeg — this is the "Mock Camera. Mock MediaMTX publisher." boundary
the feature spec calls for.
"""

from __future__ import annotations

import contextlib
import importlib.util
import threading
import time

import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.service import CameraService
from app.plugins.camera.sources import OpenCvFrameSource, Picamera2FrameSource
from app.tests.conftest import make_settings


class FakeFrameSource:
    """Yields a fixed number of frames, then signals end-of-stream."""

    def __init__(self, *, frame_count: int = 1_000_000, fail_to_open: bool = False) -> None:
        self.opened = False
        self.closed = False
        self._frame_count = frame_count
        self._read_count = 0
        self._fail_to_open = fail_to_open

    def open(self) -> None:
        if self._fail_to_open:
            raise CameraUnavailableError("camera not detected")
        self.opened = True

    def read(self) -> bytes | None:
        if self._read_count >= self._frame_count:
            return None
        self._read_count += 1
        time.sleep(0.001)  # simulate frame-capture latency without a tight busy loop
        return b"\x00" * 4

    def close(self) -> None:
        self.closed = True


class FakeStreamPublisher:
    """Records every frame it's asked to publish."""

    def __init__(
        self, *, fail_to_start: bool = False, fail_after_frames: int | None = None
    ) -> None:
        self.started = False
        self.stopped = False
        self.frames: list[bytes] = []
        self.publish_url: str | None = None
        self._fail_to_start = fail_to_start
        self._fail_after_frames = fail_after_frames

    def start(
        self, *, publish_url: str, width: int, height: int, fps: int, bitrate_kbps: int, preset: str
    ) -> None:
        if self._fail_to_start:
            raise CameraUnavailableError("ffmpeg not found")
        self.started = True
        self.publish_url = publish_url

    def write(self, frame: bytes) -> None:
        if self._fail_after_frames is not None and len(self.frames) >= self._fail_after_frames:
            raise BrokenPipeError("Broken pipe")
        self.frames.append(frame)

    def stop(self) -> None:
        self.stopped = True


def _service(
    *, frame_source: FakeFrameSource | None = None, publisher: FakeStreamPublisher | None = None
) -> tuple[CameraService, FakeFrameSource, FakeStreamPublisher]:
    settings = make_settings(
        MEDIAMTX_HOST="mediamtx.local",
        MEDIAMTX_PORT=8554,
        MEDIAMTX_PLAYBACK_PORT=8889,
        STREAM_NAME="camera",
        CAMERA_WIDTH=1280,
        CAMERA_HEIGHT=720,
        CAMERA_FPS=30,
    )
    source = frame_source or FakeFrameSource()
    pub = publisher or FakeStreamPublisher()
    service = CameraService(
        settings, frame_source_factory=lambda: source, publisher_factory=lambda: pub
    )
    return service, source, pub


def test_start_opens_the_camera_and_publisher_and_reports_status() -> None:
    service, source, publisher = _service()
    result = service.start()

    assert source.opened is True
    assert publisher.started is True
    assert result["running"] is True
    assert result["stream_name"] == "camera"
    assert result["playback_url"] == "http://mediamtx.local:8889/camera/whep"
    assert result["resolution"] == "1280x720"
    assert result["fps"] == 30
    assert result["started_at"] is not None
    assert publisher.publish_url == "rtsp://:@mediamtx.local:8554/camera"

    service.stop()


def test_start_uses_a_publish_token_as_a_query_parameter_when_given() -> None:
    """MediaMTX only runs one authMethod: once reads require a JWT, the agent's
    RTSP publish must authenticate with one too (see docs/agent/CAMERA.md).
    MediaMTX's documented mechanism for RTSP is a ?token= query parameter,
    not RTSP Basic Auth's username/password fields."""
    service, _source, publisher = _service()

    service.start(publish_token="the-jwt")

    assert publisher.publish_url == "rtsp://mediamtx.local:8554/camera?token=the-jwt"

    service.stop()


def test_start_is_idempotent_while_already_streaming() -> None:
    service, source, publisher = _service()
    first = service.start()
    second = service.start()

    assert first["started_at"] == second["started_at"]
    # A second start() must not reopen the camera or publisher.
    assert source.opened is True

    service.stop()


def test_frames_are_published_while_streaming() -> None:
    service, _source, publisher = _service()
    service.start()
    time.sleep(0.05)
    service.stop()

    assert len(publisher.frames) > 0


def test_a_pump_thread_that_dies_on_its_own_still_releases_the_camera() -> None:
    """Regression test: a stream that fails without anyone calling stop() (e.g.
    the publisher's pipe breaking) must still release frame_source/publisher
    itself. Before this fix, is_streaming correctly flipped to False but the
    camera/publisher were never released, so every subsequent start() failed
    against real hardware with "Camera in Running state" instead of a fresh
    error — this only reproduces against real picamera2/ffmpeg, so the fake
    publisher's induced failure below stands in for that broken pipe.
    """
    source = FakeFrameSource()
    publisher = FakeStreamPublisher(fail_after_frames=2)
    next_source = FakeFrameSource()
    next_publisher = FakeStreamPublisher()
    sources = [source, next_source]
    publishers = [publisher, next_publisher]
    settings = make_settings()
    service = CameraService(
        settings,
        frame_source_factory=lambda: sources.pop(0),
        publisher_factory=lambda: publishers.pop(0),
    )

    service.start()
    for _ in range(50):
        if not service.is_streaming:
            break
        time.sleep(0.01)

    assert service.is_streaming is False
    assert service.last_error is not None
    # The key assertion: cleanup ran without anyone calling stop().
    assert source.closed is True
    assert publisher.stopped is True

    # And a fresh start() must succeed — proving the "camera" is actually free.
    result = service.start()

    assert result["running"] is True
    assert next_source.opened is True
    service.stop()


def test_stop_while_not_streaming_returns_a_zeroed_success_result() -> None:
    service, _source, _publisher = _service()
    result = service.stop()

    assert result == {
        "duration": 0.0,
        "frames_sent": 0,
        "stopped_at": result["stopped_at"],
    }
    assert result["stopped_at"] is not None


def test_stop_releases_camera_and_publisher_and_reports_frames_sent() -> None:
    service, source, publisher = _service()
    service.start()
    time.sleep(0.05)
    result = service.stop()

    assert source.closed is True
    assert publisher.stopped is True
    assert result["frames_sent"] > 0
    assert result["duration"] >= 0.0
    assert service.is_streaming is False


def test_status_reports_not_running_before_any_start() -> None:
    service, _source, _publisher = _service()
    status = service.status()

    assert status["running"] is False
    assert status["started_at"] is None
    assert status["uptime_seconds"] == 0.0
    assert status["playback_url"] == "http://mediamtx.local:8889/camera/whep"


def test_playback_url_omits_the_port_when_unset() -> None:
    """A reverse proxy/load balancer terminating the scheme's implicit default
    port (443/80) needs the browser-facing URL to carry no port at all."""
    settings = make_settings(
        MEDIAMTX_HOST="media.samslab.site",
        MEDIAMTX_PLAYBACK_PORT="",
        MEDIAMTX_PLAYBACK_SCHEME="https",
        STREAM_NAME="camera",
    )
    service = CameraService(settings)

    assert service.playback_url() == "https://media.samslab.site/camera/whep"


def test_playback_url_uses_https_scheme_with_an_explicit_port() -> None:
    settings = make_settings(
        MEDIAMTX_HOST="media.samslab.site",
        MEDIAMTX_PLAYBACK_PORT=8443,
        MEDIAMTX_PLAYBACK_SCHEME="https",
        STREAM_NAME="camera",
    )
    service = CameraService(settings)

    assert service.playback_url() == "https://media.samslab.site:8443/camera/whep"


def test_status_reports_running_while_streaming() -> None:
    service, _source, _publisher = _service()
    service.start()
    status = service.status()

    assert status["running"] is True
    assert status["uptime_seconds"] >= 0.0

    service.stop()


def test_start_raises_and_records_last_error_when_the_camera_fails_to_open() -> None:
    frame_source = FakeFrameSource(fail_to_open=True)
    service, _source, _publisher = _service(frame_source=frame_source)

    try:
        service.start()
        raised = False
    except CameraUnavailableError:
        raised = True

    assert raised is True
    assert service.last_error is not None
    assert service.is_streaming is False


def test_start_raises_and_records_last_error_when_the_publisher_fails() -> None:
    publisher = FakeStreamPublisher(fail_to_start=True)
    service, _source, _publisher = _service(publisher=publisher)

    try:
        service.start()
        raised = False
    except CameraUnavailableError:
        raised = True

    assert raised is True
    assert service.last_error is not None


def test_last_error_is_cleared_by_a_subsequent_successful_start() -> None:
    settings = make_settings()
    sources = [FakeFrameSource(fail_to_open=True), FakeFrameSource()]
    publisher = FakeStreamPublisher()
    service = CameraService(
        settings, frame_source_factory=lambda: sources.pop(0), publisher_factory=lambda: publisher
    )

    with contextlib.suppress(CameraUnavailableError):
        service.start()
    assert service.last_error is not None

    service.start()  # the second factory call returns a working fake

    assert service.last_error is None
    service.stop()


def test_redacted_publish_url_never_contains_credentials() -> None:
    settings = make_settings(
        MEDIAMTX_USERNAME="agent-user",
        MEDIAMTX_PASSWORD="super-secret",
        MEDIAMTX_HOST="mediamtx.local",
        MEDIAMTX_PORT=8554,
        STREAM_NAME="camera",
    )
    service = CameraService(settings)

    redacted = service.redacted_publish_url()

    assert "agent-user" not in redacted
    assert "super-secret" not in redacted
    assert redacted == "rtsp://mediamtx.local:8554/camera"


def test_check_camera_detected_reflects_the_configured_device_path() -> None:
    settings = make_settings(CAMERA_DEVICE_INDEX=97)
    service = CameraService(settings)

    # No /dev/video97 exists on the test machine.
    assert service.check_camera_detected() is False


def test_check_camera_detected_is_true_while_streaming() -> None:
    service, _source, _publisher = _service()
    service.start()

    assert service.check_camera_detected() is True

    service.stop()


def test_check_mediamtx_reachable_is_false_for_an_unreachable_host() -> None:
    settings = make_settings(MEDIAMTX_HOST="192.0.2.1", MEDIAMTX_PORT=1)
    service = CameraService(settings)

    assert service.check_mediamtx_reachable() is False


def test_only_one_stream_thread_runs_at_a_time() -> None:
    service, _source, _publisher = _service()
    service.start()
    first_thread_count = threading.active_count()
    service.start()
    second_thread_count = threading.active_count()

    assert first_thread_count == second_thread_count

    service.stop()


def test_default_frame_source_prefers_picamera2_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CSI camera module is only reachable via libcamera/picamera2 — see
    Picamera2FrameSource's docstring for why OpenCV can never open one on
    current Raspberry Pi hardware."""
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: object() if name == "picamera2" else None
    )
    settings = make_settings()
    service = CameraService(settings)

    assert isinstance(service._frame_source_factory(), Picamera2FrameSource)


def test_default_frame_source_falls_back_to_opencv_when_picamera2_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    settings = make_settings()
    service = CameraService(settings)

    assert isinstance(service._frame_source_factory(), OpenCvFrameSource)
