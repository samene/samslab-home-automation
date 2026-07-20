"""Tests for PumpTriggerHandler: argument validation, execution, and failure paths."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import structlog

from app.commands import metrics as command_metrics
from app.commands.context import CommandContext, CommandServices
from app.commands.exceptions import CommandValidationError
from app.commands.registry import CommandRegistry
from app.health.service import HealthService
from app.plugins.camera.service import CameraService
from app.plugins.pump.exceptions import PumpBusyError
from app.plugins.pump.handlers import PumpTriggerHandler, register_pump_handlers
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings
from app.tests.test_pump_service import FakePumpGpio


def _context(*, gpio: FakePumpGpio | None = None) -> CommandContext:
    settings = make_settings()
    session = SessionState()
    plugin_manager = PluginManager()
    fake_gpio = gpio or FakePumpGpio()
    pump_service = PumpService(settings, gpio_factory=lambda: fake_gpio)
    services = CommandServices(
        plugin_manager=plugin_manager,
        health_service=HealthService(
            settings=settings, session=session, plugin_manager=plugin_manager
        ),
        registry=CommandRegistry(),
        agent_started_at=datetime.now(UTC),
        camera_service=CameraService(settings),
        pump_service=pump_service,
    )
    return CommandContext(
        command_id=uuid4(),
        command_type="pump.trigger",
        correlation_id=uuid4(),
        trace_id=None,
        device_name=settings.device_name,
        device_display_name=None,
        agent_version="0.1.0",
        settings=settings,
        logger=structlog.get_logger(__name__),
        metrics=command_metrics,
        services=services,
    )


def test_command_type_is_pump_trigger() -> None:
    assert PumpTriggerHandler().command_type == "pump.trigger"


def test_register_pump_handlers_registers_only_trigger() -> None:
    registry = CommandRegistry()
    register_pump_handlers(registry)
    assert [handler.command_type for handler in registry.list_handlers()] == ["pump.trigger"]


async def test_validate_accepts_no_arguments() -> None:
    handler = PumpTriggerHandler()
    await handler.validate(_context(), {})  # must not raise


async def test_validate_accepts_a_pulse_duration_within_bounds() -> None:
    handler = PumpTriggerHandler()
    await handler.validate(_context(), {"pulse_duration_ms": 500})  # must not raise


async def test_validate_rejects_a_pulse_duration_below_the_minimum() -> None:
    handler = PumpTriggerHandler()
    context = _context()
    too_low = context.settings.pump_trigger_pulse_min_ms - 1

    with pytest.raises(CommandValidationError):
        await handler.validate(context, {"pulse_duration_ms": too_low})


async def test_validate_rejects_a_pulse_duration_above_the_maximum() -> None:
    handler = PumpTriggerHandler()
    context = _context()
    too_high = context.settings.pump_trigger_pulse_max_ms + 1

    with pytest.raises(CommandValidationError):
        await handler.validate(context, {"pulse_duration_ms": too_high})


async def test_validate_rejects_a_non_integer_pulse_duration() -> None:
    handler = PumpTriggerHandler()

    with pytest.raises(CommandValidationError):
        await handler.validate(_context(), {"pulse_duration_ms": "200"})

    with pytest.raises(CommandValidationError):
        await handler.validate(_context(), {"pulse_duration_ms": True})


async def test_execute_triggers_the_pump_and_returns_its_result() -> None:
    handler = PumpTriggerHandler()
    context = _context()

    result = await handler.execute(context, {})

    assert result["pulse_duration_ms"] == context.settings.pump_trigger_pulse_ms
    assert result["gpio_pin"] == context.settings.pump_gpio_pin
    datetime.fromisoformat(result["triggered_at"])


async def test_execute_honors_a_pulse_duration_override() -> None:
    handler = PumpTriggerHandler()
    context = _context()

    result = await handler.execute(context, {"pulse_duration_ms": 75})

    assert result["pulse_duration_ms"] == 75


async def test_execute_propagates_a_busy_rejection() -> None:
    handler = PumpTriggerHandler()
    context = _context()
    # Pre-acquire the pump's own lock by putting it mid-trigger via a direct,
    # non-blocking acquire on its internal lock — simplest way to force the
    # busy path deterministically without real thread timing.
    context.services.pump_service._lock.acquire()  # noqa: SLF001
    try:
        with pytest.raises(PumpBusyError):
            await handler.execute(context, {})
    finally:
        context.services.pump_service._lock.release()  # noqa: SLF001
