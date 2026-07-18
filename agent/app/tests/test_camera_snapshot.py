"""Tests for CameraService.capture_snapshot(): reuse-vs-fresh-source, thumbnail
generation, temp-file cleanup, and metadata-only results.

Uses a hand-rolled fake uploader (matching this codebase's existing
FakeFrameSource/FakeStreamPublisher style, not a mocking library) so no real
network call to S3 ever happens. Real ``cv2`` (already a dependency of the
``camera`` extra) does the actual JPEG encode/resize — only the *upload* is
faked, so these tests also exercise the real encode path end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.service import CameraService
from app.plugins.camera.snapshot_uploader import SnapshotUploadResult
from app.tests.conftest import make_settings
from app.tests.test_camera_service import FakeStreamPublisher


class FakeSnapshotFrameSource:
    """A FrameSource dedicated to the "no stream active" snapshot path."""

    def __init__(self, *, width: int, height: int, fail_to_open: bool = False) -> None:
        self.width = width
        self.height = height
        self.opened = False
        self.closed = False
        self._fail_to_open = fail_to_open

    def open(self) -> None:
        if self._fail_to_open:
            raise CameraUnavailableError("camera not detected")
        self.opened = True

    def read(self) -> bytes | None:
        # An all-black frame is a valid, cheaply-constructed BGR24 buffer of
        # exactly the right size for cv2 to encode/resize for real.
        return bytes(self.width * self.height * 3)

    def close(self) -> None:
        self.closed = True


@dataclass
class _RecordedUpload:
    original_bytes: bytes
    thumbnail_bytes: bytes
    device_name: str
    captured_at: datetime


class FakeUploader:
    """Records every upload() call; never touches the network."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[_RecordedUpload] = []
        self._fail = fail

    def upload(
        self, *, original_bytes: bytes, thumbnail_bytes: bytes, device_name: str, captured_at: datetime
    ) -> SnapshotUploadResult:
        self.calls.append(_RecordedUpload(original_bytes, thumbnail_bytes, device_name, captured_at))
        if self._fail:
            raise RuntimeError("simulated S3 failure")
        return SnapshotUploadResult(
            bucket="test-bucket",
            filename="fake-uuid.jpg",
            original_object_key=f"snapshots/2026/01/01/{device_name}/original/fake-uuid.jpg",
            thumbnail_object_key=f"snapshots/2026/01/01/{device_name}/thumbnails/fake-uuid.jpg",
            etag="fake-etag",
            size=len(original_bytes),
        )


def _service(
    *,
    uploader: FakeUploader | None,
    snapshot_frame_source: FakeSnapshotFrameSource | None = None,
) -> tuple[CameraService, FakeUploader | None]:
    settings = make_settings(
        DEVICE_NAME="backyard-pi",
        CAMERA_WIDTH=64,
        CAMERA_HEIGHT=48,
        CAMERA_SNAPSHOT_WIDTH=128,
        CAMERA_SNAPSHOT_HEIGHT=96,
        CAMERA_SNAPSHOT_THUMBNAIL_WIDTH=32,
    )
    source = snapshot_frame_source or FakeSnapshotFrameSource(width=128, height=96)
    service = CameraService(
        settings,
        snapshot_frame_source_factory=lambda: source,
        uploader=uploader,
    )
    return service, uploader


def test_capture_snapshot_raises_when_no_uploader_is_configured() -> None:
    settings = make_settings()  # no AWS_* settings -> build_s3_snapshot_uploader returns None
    service = CameraService(settings)

    with pytest.raises(CameraUnavailableError, match="not configured"):
        service.capture_snapshot()


def test_capture_snapshot_opens_and_closes_a_fresh_frame_source_when_idle() -> None:
    uploader = FakeUploader()
    frame_source = FakeSnapshotFrameSource(width=128, height=96)
    service, _ = _service(uploader=uploader, snapshot_frame_source=frame_source)

    result = service.capture_snapshot()

    assert frame_source.opened is True
    assert frame_source.closed is True
    assert result["reused_stream"] is False
    assert result["width"] == 128
    assert result["height"] == 96
    assert len(uploader.calls) == 1


def test_capture_snapshot_reuses_the_live_frame_source_while_streaming() -> None:
    uploader = FakeUploader()
    snapshot_source = FakeSnapshotFrameSource(width=128, height=96)
    settings = make_settings(
        DEVICE_NAME="backyard-pi", CAMERA_WIDTH=64, CAMERA_HEIGHT=48, CAMERA_SNAPSHOT_WIDTH=128
    )
    # A real, size-correct frame source for the *live* path: unlike
    # test_camera_service.py's FakeFrameSource (which returns a fixed 4-byte
    # dummy frame, fine for streaming tests that never decode it),
    # capture_snapshot's reuse path actually reshapes/encodes the frame, so
    # it needs a buffer matching camera_width x camera_height x 3 bytes.
    live_source = FakeSnapshotFrameSource(width=64, height=48)
    service = CameraService(
        settings,
        frame_source_factory=lambda: live_source,
        publisher_factory=FakeStreamPublisher,
        snapshot_frame_source_factory=lambda: snapshot_source,
        uploader=uploader,
    )
    service.start()

    result = service.capture_snapshot()

    assert result["reused_stream"] is True
    assert result["width"] == 64
    assert result["height"] == 48
    # The dedicated snapshot-only frame source must never be touched while streaming.
    assert snapshot_source.opened is False
    # The live session keeps running — capturing a snapshot must not stop it.
    assert service.is_streaming is True

    service.stop()


def test_capture_snapshot_returns_metadata_only_never_image_bytes() -> None:
    uploader = FakeUploader()
    service, _ = _service(uploader=uploader)

    result = service.capture_snapshot()

    expected_keys = {
        "bucket",
        "filename",
        "original_object_key",
        "thumbnail_object_key",
        "etag",
        "sha256",
        "width",
        "height",
        "size",
        "captured_at",
        "reused_stream",
        "capture_duration",
        "upload_duration",
    }
    assert set(result.keys()) == expected_keys
    assert all(not isinstance(value, bytes) for value in result.values())


def test_capture_snapshot_computes_sha256_over_the_original_image_bytes() -> None:
    import hashlib

    uploader = FakeUploader()
    service, _ = _service(uploader=uploader)

    result = service.capture_snapshot()

    assert len(uploader.calls) == 1
    expected_sha256 = hashlib.sha256(uploader.calls[0].original_bytes).hexdigest()
    assert result["sha256"] == expected_sha256


def test_capture_snapshot_generates_a_thumbnail_at_the_configured_width() -> None:
    uploader = FakeUploader()
    service, _ = _service(uploader=uploader)

    service.capture_snapshot()

    thumbnail_bytes = uploader.calls[0].thumbnail_bytes
    decoded = cv2.imdecode(np.frombuffer(thumbnail_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[1] == 32  # CAMERA_SNAPSHOT_THUMBNAIL_WIDTH from _service()'s settings
    # Aspect ratio (128x96 -> 4:3) preserved: 32 wide -> 24 tall.
    assert decoded.shape[0] == 24


def test_capture_snapshot_deletes_temp_files_after_successful_upload() -> None:
    uploader = FakeUploader()
    service, _ = _service(uploader=uploader)

    service.capture_snapshot()

    settings = make_settings(CAMERA_SNAPSHOT_WIDTH=128, CAMERA_SNAPSHOT_HEIGHT=96)
    leftover = list(settings.tmp_directory.glob("snapshot-*"))
    assert leftover == []


def test_capture_snapshot_deletes_temp_files_even_when_upload_fails() -> None:
    uploader = FakeUploader(fail=True)
    service, _ = _service(uploader=uploader)

    with pytest.raises(CameraUnavailableError, match="Failed to upload"):
        service.capture_snapshot()

    settings = make_settings()
    leftover = list(settings.tmp_directory.glob("snapshot-*"))
    assert leftover == []


def test_capture_snapshot_raises_when_the_camera_returns_no_frame() -> None:
    class _EmptyFrameSource(FakeSnapshotFrameSource):
        def read(self) -> bytes | None:
            return None

    uploader = FakeUploader()
    frame_source = _EmptyFrameSource(width=128, height=96)
    service, _ = _service(uploader=uploader, snapshot_frame_source=frame_source)

    with pytest.raises(CameraUnavailableError, match="no frame"):
        service.capture_snapshot()

    assert uploader.calls == []
