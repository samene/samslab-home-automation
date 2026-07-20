"""Tests for the camera.stream.start/stop and camera.status command handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.commands import metrics as command_metrics
from app.commands.context import CommandContext, CommandServices
from app.commands.registry import CommandRegistry
from app.health.service import HealthService
from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.handlers import (
    CameraSnapshotHandler,
    CameraStatusHandler,
    CameraStreamStartHandler,
    CameraStreamStopHandler,
    register_camera_handlers,
)
from app.plugins.camera.service import CameraService
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings
from app.tests.test_camera_service import FakeFrameSource, FakeStreamPublisher
from app.tests.test_camera_snapshot import FakeSnapshotFrameSource, FakeUploader


def _context(camera_service: CameraService, registry: CommandRegistry) -> CommandContext:
    settings = make_settings()
    session = SessionState()
    plugin_manager = PluginManager()
    services = CommandServices(
        plugin_manager=plugin_manager,
        health_service=HealthService(
            settings=settings, session=session, plugin_manager=plugin_manager
        ),
        registry=registry,
        agent_started_at=datetime.now(UTC),
        camera_service=camera_service,
        pump_service=PumpService(settings),
    )
    return CommandContext(
        command_id=uuid4(),
        command_type="camera.test",
        correlation_id=None,
        trace_id=None,
        device_name=settings.device_name,
        device_display_name=settings.device_display_name,
        agent_version="0.1.0",
        settings=settings,
        logger=_NullLogger(),
        metrics=command_metrics,
        services=services,
    )


class _NullLogger:
    """A structlog-shaped logger that discards everything, for handler tests."""

    def info(self, *args: object, **kwargs: object) -> None:
        pass

    def warning(self, *args: object, **kwargs: object) -> None:
        pass


def _camera_service() -> CameraService:
    settings = make_settings(
        MEDIAMTX_HOST="mediamtx.local", MEDIAMTX_PLAYBACK_PORT=8889, STREAM_NAME="camera"
    )
    return CameraService(
        settings,
        frame_source_factory=FakeFrameSource,
        publisher_factory=FakeStreamPublisher,
    )


def test_register_camera_handlers_registers_all_six() -> None:
    registry = CommandRegistry()
    register_camera_handlers(registry)

    types = {handler.command_type for handler in registry.list_handlers()}
    assert types == {
        "camera.stream.start",
        "camera.stream.stop",
        "camera.status",
        "camera.snapshot",
        "camera.record.start",
        "camera.record.stop",
    }


async def test_start_handler_returns_stream_info() -> None:
    camera_service = _camera_service()
    context = _context(camera_service, CommandRegistry())
    handler = CameraStreamStartHandler()

    await handler.validate(context, {})
    result = await handler.execute(context, {})

    assert result["stream_name"] == "camera"
    assert result["playback_url"] == "http://mediamtx.local:8889/camera/index.m3u8"
    assert result["started_at"] is not None

    camera_service.stop()


async def test_start_handler_passes_the_publish_token_through_to_the_camera_service() -> None:
    """The command payload's mediamtx_publish_token must reach the RTSP publish URL."""
    settings = make_settings(
        MEDIAMTX_HOST="mediamtx.local", MEDIAMTX_PLAYBACK_PORT=8889, STREAM_NAME="camera"
    )
    publisher = FakeStreamPublisher()
    camera_service = CameraService(
        settings,
        frame_source_factory=FakeFrameSource,
        publisher_factory=lambda: publisher,
    )
    context = _context(camera_service, CommandRegistry())
    handler = CameraStreamStartHandler()

    await handler.execute(context, {"mediamtx_publish_token": "the-jwt"})

    assert publisher.publish_url == "rtsp://mediamtx.local:8554/camera?token=the-jwt"

    camera_service.stop()


async def test_stop_handler_returns_duration_and_frames_sent() -> None:
    camera_service = _camera_service()
    context = _context(camera_service, CommandRegistry())
    await CameraStreamStartHandler().execute(context, {})

    result = await CameraStreamStopHandler().execute(context, {})

    assert "duration" in result
    assert "frames_sent" in result
    assert result["stopped_at"] is not None


async def test_status_handler_reports_running_state() -> None:
    camera_service = _camera_service()
    context = _context(camera_service, CommandRegistry())

    idle_status = await CameraStatusHandler().execute(context, {})
    assert idle_status["running"] is False

    await CameraStreamStartHandler().execute(context, {})
    running_status = await CameraStatusHandler().execute(context, {})
    assert running_status["running"] is True
    assert running_status["playback_url"] == "http://mediamtx.local:8889/camera/index.m3u8"

    camera_service.stop()


async def test_start_handler_propagates_camera_unavailable_errors() -> None:
    settings = make_settings()
    failing_source = FakeFrameSource(fail_to_open=True)
    camera_service = CameraService(
        settings, frame_source_factory=lambda: failing_source, publisher_factory=FakeStreamPublisher
    )
    context = _context(camera_service, CommandRegistry())

    with pytest.raises(CameraUnavailableError, match="camera not detected"):
        await CameraStreamStartHandler().execute(context, {})


def _snapshot_camera_service(*, uploader: FakeUploader | None) -> CameraService:
    settings = make_settings(
        DEVICE_NAME="backyard-pi", CAMERA_SNAPSHOT_WIDTH=64, CAMERA_SNAPSHOT_HEIGHT=48
    )
    frame_source = FakeSnapshotFrameSource(width=64, height=48)
    return CameraService(
        settings, snapshot_frame_source_factory=lambda: frame_source, uploader=uploader
    )


async def test_snapshot_handler_returns_metadata_only() -> None:
    camera_service = _snapshot_camera_service(uploader=FakeUploader())
    context = _context(camera_service, CommandRegistry())
    handler = CameraSnapshotHandler()

    await handler.validate(context, {})
    result = await handler.execute(context, {})

    assert result["bucket"] == "test-bucket"
    assert result["width"] == 64
    assert result["height"] == 48
    assert result["captured_at"] is not None
    assert "image" not in result and "bytes" not in result


async def test_snapshot_handler_propagates_camera_unavailable_when_s3_is_unconfigured() -> None:
    camera_service = _snapshot_camera_service(uploader=None)
    context = _context(camera_service, CommandRegistry())
    handler = CameraSnapshotHandler()

    with pytest.raises(CameraUnavailableError, match="not configured"):
        await handler.execute(context, {})
