"""Tests for CommandContext and build_command_context."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.commands import metrics as command_metrics
from app.commands.context import CommandServices, build_command_context
from app.commands.registry import CommandRegistry
from app.health.service import HealthService
from app.plugins.camera.service import CameraService
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import CommandPayload, Envelope


def _services() -> CommandServices:
    settings = make_settings()
    session = SessionState()
    plugin_manager = PluginManager()
    return CommandServices(
        plugin_manager=plugin_manager,
        health_service=HealthService(
            settings=settings, session=session, plugin_manager=plugin_manager
        ),
        registry=CommandRegistry(),
        agent_started_at=datetime.now(UTC),
        camera_service=CameraService(settings),
        pump_service=PumpService(settings),
    )


def test_build_command_context_populates_identifiers() -> None:
    """Envelope/payload identifiers flow through into the context unchanged."""
    settings = make_settings(DEVICE_NAME="pi-01", DEVICE_DISPLAY_NAME="Greenhouse Pi")
    command_id = uuid4()
    correlation_id = uuid4()
    envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.COMMAND,
        payload={},
        correlation_id=correlation_id,
        trace_id="trace-123",
    )
    payload = CommandPayload(command_id=command_id, command_type="system.echo", arguments={})

    context = build_command_context(
        envelope=envelope,
        payload=payload,
        settings=settings,
        services=_services(),
        agent_version="9.9.9",
        logger=None,
    )

    assert context.command_id == command_id
    assert context.command_type == "system.echo"
    assert context.correlation_id == correlation_id
    assert context.trace_id == "trace-123"
    assert context.device_name == "pi-01"
    assert context.device_display_name == "Greenhouse Pi"
    assert context.agent_version == "9.9.9"
    assert context.settings is settings
    assert context.metrics is command_metrics


def test_build_command_context_allows_missing_correlation_and_trace_ids() -> None:
    """A minimal envelope with no correlation/trace ID still builds a valid context."""
    envelope = Envelope(protocol_version=1, message_type=MessageType.COMMAND, payload={})
    payload = CommandPayload(command_id=uuid4(), command_type="system.ping", arguments={})

    context = build_command_context(
        envelope=envelope,
        payload=payload,
        settings=make_settings(),
        services=_services(),
        agent_version="0.1.0",
        logger=None,
    )

    assert context.correlation_id is None
    assert context.trace_id is None


def test_command_context_is_immutable() -> None:
    """CommandContext is a frozen dataclass."""
    envelope = Envelope(protocol_version=1, message_type=MessageType.COMMAND, payload={})
    payload = CommandPayload(command_id=uuid4(), command_type="system.ping", arguments={})
    context = build_command_context(
        envelope=envelope,
        payload=payload,
        settings=make_settings(),
        services=_services(),
        agent_version="0.1.0",
        logger=None,
    )

    with pytest.raises(AttributeError):
        context.command_type = "system.other"  # type: ignore[misc]


def test_command_services_is_immutable() -> None:
    """CommandServices is a frozen dataclass."""
    services = _services()
    with pytest.raises(AttributeError):
        services.agent_started_at = datetime.now(UTC)  # type: ignore[misc]
