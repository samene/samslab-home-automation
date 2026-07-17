"""Tests for the four built-in system.* command handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.commands import metrics as command_metrics
from app.commands.builtin import (
    SystemCapabilitiesHandler,
    SystemEchoHandler,
    SystemHealthHandler,
    SystemPingHandler,
    register_builtin_handlers,
)
from app.commands.context import CommandContext, CommandServices
from app.commands.registry import CommandRegistry
from app.health.service import HealthService
from app.plugins.base import Plugin
from app.plugins.camera.service import CameraService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings


def _context(
    *, plugin_manager: PluginManager | None = None, registry: CommandRegistry | None = None
) -> CommandContext:
    settings = make_settings()
    session = SessionState()
    plugins = plugin_manager or PluginManager()
    services = CommandServices(
        plugin_manager=plugins,
        health_service=HealthService(settings=settings, session=session, plugin_manager=plugins),
        registry=registry or CommandRegistry(),
        agent_started_at=datetime.now(UTC) - timedelta(seconds=42),
        camera_service=CameraService(settings),
    )
    return CommandContext(
        command_id=uuid4(),
        command_type="system.test",
        correlation_id=None,
        trace_id=None,
        device_name=settings.device_name,
        device_display_name=settings.device_display_name,
        agent_version="1.2.3",
        settings=settings,
        logger=None,
        metrics=command_metrics,
        services=services,
    )


def test_register_builtin_handlers_registers_all_four() -> None:
    """register_builtin_handlers() registers exactly the four documented system.* types."""
    registry = CommandRegistry()
    register_builtin_handlers(registry)

    command_types = {handler.command_type for handler in registry.list_handlers()}
    assert command_types == {"system.echo", "system.ping", "system.capabilities", "system.health"}


@pytest.mark.asyncio
async def test_system_echo_returns_arguments_unchanged() -> None:
    """system.echo returns exactly what it was given."""
    handler = SystemEchoHandler()
    context = _context()
    arguments = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}

    await handler.validate(context, arguments)
    result = await handler.execute(context, arguments)

    assert result == arguments


@pytest.mark.asyncio
async def test_system_ping_returns_status_timestamp_version_and_uptime() -> None:
    """system.ping reports liveness, agent version, and uptime since agent start."""
    handler = SystemPingHandler()
    context = _context()

    result = await handler.execute(context, {})

    assert result["status"] == "ok"
    assert result["agent_version"] == "1.2.3"
    assert result["uptime_seconds"] >= 42
    # timestamp is a real, parseable ISO datetime
    datetime.fromisoformat(result["timestamp"])


@pytest.mark.asyncio
async def test_system_capabilities_reports_plugins_and_handlers() -> None:
    """system.capabilities reports registered plugins, handlers, capabilities, and versions."""

    class _StubPlugin(Plugin):
        name = "stub-plugin"
        capabilities = ("gpio", "camera")

    plugin_manager = PluginManager([_StubPlugin()])
    registry = CommandRegistry()
    register_builtin_handlers(registry)
    context = _context(plugin_manager=plugin_manager, registry=registry)
    handler = SystemCapabilitiesHandler()

    result = await handler.execute(context, {})

    assert result["plugins"] == [{"name": "stub-plugin", "capabilities": ["gpio", "camera"]}]
    assert set(result["command_handlers"]) == {
        "system.echo",
        "system.ping",
        "system.capabilities",
        "system.health",
    }
    assert set(result["capabilities"]) == {"gpio", "camera"}
    assert result["versions"] == {"agent_version": "1.2.3", "protocol_version": 1}


@pytest.mark.asyncio
async def test_system_health_reports_health_service_state() -> None:
    """system.health reflects the health subsystem's current combined report."""
    handler = SystemHealthHandler()
    context = _context()

    result = await handler.execute(context, {})

    assert result["state"] in {"HEALTHY", "DEGRADED", "UNHEALTHY"}
    names = {check["name"] for check in result["checks"]}
    assert names == {"connection", "configuration", "plugins", "memory", "disk"}


@pytest.mark.asyncio
async def test_all_builtin_handlers_accept_empty_arguments_validation() -> None:
    """Every non-echo built-in accepts an empty argument set without raising."""
    context = _context()
    for handler in (SystemPingHandler(), SystemCapabilitiesHandler(), SystemHealthHandler()):
        await handler.validate(context, {})
