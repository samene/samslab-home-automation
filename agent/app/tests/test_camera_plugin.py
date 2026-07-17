"""Tests for CameraPlugin: health reporting and shutdown behavior."""

from __future__ import annotations

import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.plugin import CameraPlugin
from app.plugins.camera.service import CameraService
from app.tests.conftest import make_settings
from app.tests.test_camera_service import FakeFrameSource, FakeStreamPublisher


def _plugin() -> tuple[CameraPlugin, CameraService, FakeFrameSource, FakeStreamPublisher]:
    settings = make_settings()
    source = FakeFrameSource()
    publisher = FakeStreamPublisher()
    service = CameraService(
        settings, frame_source_factory=lambda: source, publisher_factory=lambda: publisher
    )
    return CameraPlugin(service), service, source, publisher


def test_advertises_the_camera_capability() -> None:
    plugin, _service, _source, _publisher = _plugin()
    assert plugin.name == "camera"
    assert "camera" in plugin.capabilities


def test_check_health_is_healthy_when_idle_and_never_used() -> None:
    plugin, _service, _source, _publisher = _plugin()
    result = plugin.check_health()

    assert result.healthy is True
    assert result.detail is not None
    assert "streaming=False" in result.detail


def test_check_health_is_healthy_while_streaming() -> None:
    plugin, service, _source, _publisher = _plugin()
    service.start()

    result = plugin.check_health()

    assert result.healthy is True
    assert "streaming=True" in (result.detail or "")

    service.stop()


def test_check_health_is_unhealthy_after_a_recorded_failure() -> None:
    settings = make_settings()
    failing_source = FakeFrameSource(fail_to_open=True)
    service = CameraService(
        settings,
        frame_source_factory=lambda: failing_source,
        publisher_factory=FakeStreamPublisher,
    )
    plugin = CameraPlugin(service)

    with pytest.raises(CameraUnavailableError):
        service.start()

    result = plugin.check_health()

    assert result.healthy is False
    assert result.detail == service.last_error


async def test_on_shutdown_stops_an_in_progress_stream() -> None:
    plugin, service, _source, publisher = _plugin()
    service.start()
    assert service.is_streaming is True

    await plugin.on_shutdown()

    assert service.is_streaming is False
    assert publisher.stopped is True


async def test_on_shutdown_is_a_no_op_when_not_streaming() -> None:
    plugin, service, _source, _publisher = _plugin()

    await plugin.on_shutdown()

    assert service.is_streaming is False
