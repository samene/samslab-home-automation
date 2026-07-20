"""Tests for CameraService.start_recording()/stop_recording(): reject-while-
streaming, temp-file cleanup, max-duration safety valve, and metadata-only
results.

Uses hand-rolled fakes (matching this codebase's existing
FakeFrameSource/FakeStreamPublisher/FakeUploader style, not a mocking
library) for the frame source, the Mp4Recorder, and the S3 uploader — no
real ffmpeg subprocess or network call ever happens.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.recording_uploader import RecordingUploadResult
from app.plugins.camera.service import CameraService
from app.tests.conftest import make_settings
from app.tests.test_camera_service import FakeFrameSource, FakeStreamPublisher


class FakeRecordingFrameSource:
    """A FrameSource dedicated to the recording path.

    ``frame_bytes`` defaults to a tiny 3-byte dummy — fine for tests that
    never decode a frame — but real-frame-shape tests (e.g. thumbnail
    encoding) pass a properly sized BGR24 buffer instead.
    """

    def __init__(
        self,
        *,
        frame_count: int = 1_000_000,
        fail_to_open: bool = False,
        frame_bytes: bytes = b"\x00\x01\x02",
    ) -> None:
        self.opened = False
        self.closed = False
        self._frame_count = frame_count
        self._read_count = 0
        self._fail_to_open = fail_to_open
        self._frame_bytes = frame_bytes

    def open(self) -> None:
        if self._fail_to_open:
            raise CameraUnavailableError("camera not detected")
        self.opened = True

    def read(self) -> bytes | None:
        if self._read_count >= self._frame_count:
            return None
        self._read_count += 1
        time.sleep(0.001)
        return self._frame_bytes

    def close(self) -> None:
        self.closed = True


class FakeRecorder:
    """Records every frame it's asked to write; never touches ffmpeg."""

    def __init__(self, *, fail_to_start: bool = False) -> None:
        self.started = False
        self.stopped = False
        self.frames: list[bytes] = []
        self.output_path: Path | None = None
        self._fail_to_start = fail_to_start

    def start(
        self, *, output_path: Path, width: int, height: int, fps: int, bitrate_kbps: int, preset: str
    ) -> None:
        if self._fail_to_start:
            raise CameraUnavailableError("ffmpeg not found")
        self.started = True
        self.output_path = output_path
        # A real (tiny) file must exist on disk for stop_recording's
        # sha256/upload/unlink steps to operate on, matching what a real
        # ffmpeg subprocess would have actually written by the time stop()
        # returns.
        output_path.write_bytes(b"fake-mp4-bytes")

    def write(self, frame: bytes) -> None:
        self.frames.append(frame)

    def stop(self) -> None:
        self.stopped = True


@dataclass
class _RecordedUpload:
    file_path: Path
    device_name: str
    recorded_at: datetime
    thumbnail_bytes: bytes | None = None


class FakeRecordingUploader:
    """Records every upload() call; never touches the network."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[_RecordedUpload] = []
        self._fail = fail

    def upload(
        self,
        *,
        file_path: Path,
        device_name: str,
        recorded_at: datetime,
        thumbnail_bytes: bytes | None = None,
    ) -> RecordingUploadResult:
        self.calls.append(_RecordedUpload(file_path, device_name, recorded_at, thumbnail_bytes))
        if self._fail:
            raise RuntimeError("simulated S3 failure")
        return RecordingUploadResult(
            bucket="test-bucket",
            filename="fake-uuid.mp4",
            object_key=f"videos/2026/01/01/{device_name}/fake-uuid.mp4",
            thumbnail_object_key=(
                f"videos/2026/01/01/{device_name}/thumbnails/fake-uuid.jpg"
                if thumbnail_bytes is not None
                else None
            ),
            etag="fake-etag",
            size=file_path.stat().st_size,
        )


def _service(
    *,
    uploader: FakeRecordingUploader | None,
    frame_source: FakeRecordingFrameSource | None = None,
    recorder: FakeRecorder | None = None,
    **setting_overrides: object,
) -> tuple[CameraService, FakeRecordingFrameSource, FakeRecorder]:
    settings = make_settings(
        DEVICE_NAME="backyard-pi",
        CAMERA_RECORD_WIDTH=64,
        CAMERA_RECORD_HEIGHT=48,
        CAMERA_RECORD_FPS=10,
        **setting_overrides,
    )
    source = frame_source or FakeRecordingFrameSource()
    rec = recorder or FakeRecorder()
    service = CameraService(
        settings,
        recording_frame_source_factory=lambda: source,
        recorder_factory=lambda: rec,
        recording_uploader=uploader,
    )
    return service, source, rec


def test_start_recording_opens_the_frame_source_and_recorder() -> None:
    service, source, recorder = _service(uploader=FakeRecordingUploader())

    result = service.start_recording()

    assert source.opened is True
    assert recorder.started is True
    assert result["status"] == "recording_started"
    assert result["width"] == 64
    assert result["height"] == 48
    assert result["fps"] == 10
    assert result["filename"].startswith("recording-")
    assert result["started_at"] is not None
    assert service.is_recording is True

    service.stop_recording()


def test_recording_toggles_sensor_hdr_on_at_start_and_off_at_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors rpicam-vid --hdr sensor: on for the whole recording, off again
    once the pump thread releases the camera — never touching live streaming."""
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.plugins.camera.service.set_imx708_sensor_hdr", lambda enabled: calls.append(enabled)
    )
    service, _source, _recorder = _service(uploader=FakeRecordingUploader())

    service.start_recording()
    assert calls == [True]

    service.stop_recording()
    assert calls == [True, False]


def test_recording_skips_sensor_hdr_when_disabled_via_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.plugins.camera.service.set_imx708_sensor_hdr", lambda enabled: calls.append(enabled)
    )
    service, _source, _recorder = _service(
        uploader=FakeRecordingUploader(), CAMERA_HDR_SENSOR_MODE=False
    )

    service.start_recording()
    service.stop_recording()

    assert calls == []


def test_start_recording_is_idempotent_while_already_recording() -> None:
    service, _source, _recorder = _service(uploader=FakeRecordingUploader())

    first = service.start_recording()
    second = service.start_recording()

    assert first["filename"] == second["filename"]
    assert first["started_at"] == second["started_at"]

    service.stop_recording()


def test_start_recording_raises_while_a_live_stream_is_active() -> None:
    """The resolved design decision: recording never shares the one open
    camera handle with an active live stream — it rejects instead."""
    settings = make_settings(DEVICE_NAME="backyard-pi")
    service = CameraService(
        settings,
        frame_source_factory=FakeFrameSource,
        publisher_factory=FakeStreamPublisher,
        recording_uploader=FakeRecordingUploader(),
    )
    service.start()

    with pytest.raises(CameraUnavailableError, match="live stream is active"):
        service.start_recording()

    service.stop()


def test_start_recording_raises_when_the_camera_fails_to_open() -> None:
    frame_source = FakeRecordingFrameSource(fail_to_open=True)
    service, _source, _recorder = _service(
        uploader=FakeRecordingUploader(), frame_source=frame_source
    )

    with pytest.raises(CameraUnavailableError, match="camera not detected"):
        service.start_recording()

    assert service.is_recording is False


def test_stop_recording_raises_when_nothing_is_recording() -> None:
    service, _source, _recorder = _service(uploader=FakeRecordingUploader())

    with pytest.raises(CameraUnavailableError, match="no recording in progress"):
        service.stop_recording()


def test_stop_recording_finalizes_uploads_and_returns_metadata() -> None:
    uploader = FakeRecordingUploader()
    service, _source, recorder = _service(uploader=uploader)
    service.start_recording()
    time.sleep(0.05)

    result = service.stop_recording()

    assert recorder.stopped is True
    assert result["bucket"] == "test-bucket"
    assert result["object_key"] == "videos/2026/01/01/backyard-pi/fake-uuid.mp4"
    assert result["width"] == 64
    assert result["height"] == 48
    assert result["fps"] == 10
    assert result["duration"] >= 0
    assert result["file_size"] > 0
    assert result["sha256"] is not None
    assert result["recorded_at"] is not None
    assert result["upload_duration"] >= 0
    assert len(uploader.calls) == 1
    assert service.is_recording is False


def test_stop_recording_deletes_the_temp_file_after_successful_upload() -> None:
    service, _source, recorder = _service(uploader=FakeRecordingUploader())
    service.start_recording()

    service.stop_recording()

    assert recorder.output_path is not None
    assert not recorder.output_path.exists()


def test_stop_recording_deletes_the_temp_file_even_when_upload_fails() -> None:
    service, _source, recorder = _service(uploader=FakeRecordingUploader(fail=True))
    service.start_recording()

    with pytest.raises(CameraUnavailableError, match="Failed to upload"):
        service.stop_recording()

    assert recorder.output_path is not None
    assert not recorder.output_path.exists()
    # The failure must not leave the service permanently wedged as "recording".
    assert service.is_recording is False


def test_stop_recording_raises_when_no_uploader_is_configured() -> None:
    service, _source, _recorder = _service(uploader=None)
    service.start_recording()

    with pytest.raises(CameraUnavailableError, match="not configured"):
        service.stop_recording()


def test_stop_recording_computes_sha256_over_the_finalized_file() -> None:
    import hashlib

    service, _source, _recorder = _service(uploader=FakeRecordingUploader())
    service.start_recording()

    result = service.stop_recording()

    # FakeRecorder.start() always writes this exact content (see its
    # docstring) — a real ffmpeg subprocess would instead leave the actual
    # encoded MP4 bytes on disk for stop_recording() to hash the same way.
    expected_sha256 = hashlib.sha256(b"fake-mp4-bytes").hexdigest()
    assert result["sha256"] == expected_sha256


def test_stop_recording_uploads_a_thumbnail_from_the_first_frame() -> None:
    """The pump thread's first real-shaped frame gets encoded and uploaded
    alongside the video, and the result surfaces its object key."""
    uploader = FakeRecordingUploader()
    frame_source = FakeRecordingFrameSource(frame_bytes=bytes(64 * 48 * 3))
    service, _source, _recorder = _service(uploader=uploader, frame_source=frame_source)
    service.start_recording()
    time.sleep(0.05)

    result = service.stop_recording()

    assert len(uploader.calls) == 1
    assert uploader.calls[0].thumbnail_bytes is not None
    assert result["thumbnail_object_key"] is not None
    assert result["thumbnail_object_key"].endswith(".jpg")


def test_stop_recording_omits_thumbnail_when_frame_shape_cant_be_encoded() -> None:
    """A frame that can't be reshaped to width x height x 3 (e.g. the tiny
    3-byte dummy the default fake frame source returns) must not fail the
    whole recording — the thumbnail is best-effort only."""
    uploader = FakeRecordingUploader()
    service, _source, _recorder = _service(uploader=uploader)
    service.start_recording()
    time.sleep(0.02)

    result = service.stop_recording()

    assert uploader.calls[0].thumbnail_bytes is None
    assert result["thumbnail_object_key"] is None


def test_second_start_recording_after_max_duration_auto_stop_raises_pending_upload() -> None:
    """Regression test for the camera_record_max_duration_seconds safety
    valve: once the pump thread auto-exits, the local file is still pending
    upload — a fresh start_recording() must not silently strand it."""
    service, _source, _recorder = _service(
        uploader=FakeRecordingUploader(), CAMERA_RECORD_MAX_DURATION_SECONDS=0.01
    )
    service.start_recording()

    for _ in range(200):
        if not service.is_recording:
            break
        time.sleep(0.01)
    assert service.is_recording is False

    with pytest.raises(CameraUnavailableError, match="pending upload"):
        service.start_recording()

    # But an explicit stop_recording() still finalizes/uploads it correctly.
    result = service.stop_recording()
    assert result["bucket"] == "test-bucket"


def test_only_one_recording_thread_runs_at_a_time() -> None:
    import threading

    service, _source, _recorder = _service(uploader=FakeRecordingUploader())
    service.start_recording()
    first_thread_count = threading.active_count()
    service.start_recording()
    second_thread_count = threading.active_count()

    assert first_thread_count == second_thread_count

    service.stop_recording()
