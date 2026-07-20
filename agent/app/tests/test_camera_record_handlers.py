"""Tests for the camera.record.start/camera.record.stop command handlers."""

from __future__ import annotations

import pytest

from app.commands.registry import CommandRegistry
from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.handlers import CameraRecordStartHandler, CameraRecordStopHandler
from app.plugins.camera.service import CameraService
from app.tests.conftest import make_settings
from app.tests.test_camera_handlers import _context
from app.tests.test_camera_recording import FakeRecordingFrameSource, FakeRecordingUploader


def _recording_camera_service(*, uploader: FakeRecordingUploader | None) -> CameraService:
    settings = make_settings(
        DEVICE_NAME="backyard-pi", CAMERA_RECORD_WIDTH=64, CAMERA_RECORD_HEIGHT=48
    )
    frame_source = FakeRecordingFrameSource()
    return CameraService(
        settings, recording_frame_source_factory=lambda: frame_source, recording_uploader=uploader
    )


async def test_record_start_handler_returns_recording_info() -> None:
    camera_service = _recording_camera_service(uploader=FakeRecordingUploader())
    context = _context(camera_service, CommandRegistry())
    handler = CameraRecordStartHandler()

    await handler.validate(context, {})
    result = await handler.execute(context, {})

    assert result["status"] == "recording_started"
    assert result["width"] == 64
    assert result["height"] == 48
    assert result["started_at"] is not None

    camera_service.stop_recording()


async def test_record_start_handler_propagates_camera_unavailable_errors() -> None:
    failing_source = FakeRecordingFrameSource(fail_to_open=True)
    settings = make_settings(DEVICE_NAME="backyard-pi")
    camera_service = CameraService(
        settings,
        recording_frame_source_factory=lambda: failing_source,
        recording_uploader=FakeRecordingUploader(),
    )
    context = _context(camera_service, CommandRegistry())

    with pytest.raises(CameraUnavailableError, match="camera not detected"):
        await CameraRecordStartHandler().execute(context, {})


async def test_record_stop_handler_returns_metadata_only() -> None:
    camera_service = _recording_camera_service(uploader=FakeRecordingUploader())
    context = _context(camera_service, CommandRegistry())
    await CameraRecordStartHandler().execute(context, {})

    result = await CameraRecordStopHandler().execute(context, {})

    assert result["bucket"] == "test-bucket"
    assert result["object_key"].startswith("videos/")
    assert result["recorded_at"] is not None
    assert "image" not in result and "bytes" not in result


async def test_record_stop_handler_propagates_camera_unavailable_when_nothing_is_recording() -> None:
    camera_service = _recording_camera_service(uploader=FakeRecordingUploader())
    context = _context(camera_service, CommandRegistry())

    with pytest.raises(CameraUnavailableError, match="no recording in progress"):
        await CameraRecordStopHandler().execute(context, {})
