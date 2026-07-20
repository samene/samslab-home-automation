"""Tests for CommandDispatcher: the ack/execute/result pipeline and its exception safety net."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.commands.context import CommandContext, CommandServices
from app.commands.dispatcher import CommandDispatcher
from app.commands.events import CommandEvent, CommandEventBus
from app.commands.exceptions import CommandValidationError
from app.commands.executor import CommandExecutor
from app.commands.handler import CommandHandler
from app.commands.lifecycle import CommandLifecycleState
from app.commands.registry import CommandRegistry
from app.health.service import HealthService
from app.plugins.camera.service import CameraService
from app.plugins.pump.service import PumpService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import CommandPayload, CommandResultPayload, Envelope


class _EchoHandler(CommandHandler):
    @property
    def command_type(self) -> str:
        return "test.echo"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        pass

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return dict(arguments)


class _RejectingHandler(CommandHandler):
    @property
    def command_type(self) -> str:
        return "test.rejected"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        raise CommandValidationError("nope")

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return {}


class _BlockingHandler(CommandHandler):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def command_type(self) -> str:
        return "test.blocking"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        pass

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.started.set()
        await self.release.wait()
        return {"done": True}


class FakeSender:
    """Collects every envelope handed to ``send``; can be told to fail on demand."""

    def __init__(self) -> None:
        self.sent: list[Envelope] = []
        self.fail_next = False

    async def send(self, envelope: Envelope) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("send failed")
        self.sent.append(envelope)


def _make_dispatcher(
    *, registry: CommandRegistry | None = None, sender: FakeSender | None = None
) -> tuple[CommandDispatcher, FakeSender, CommandEventBus]:
    settings = make_settings()
    plugin_manager = PluginManager()
    session = SessionState()
    reg = registry or CommandRegistry()
    services = CommandServices(
        plugin_manager=plugin_manager,
        health_service=HealthService(
            settings=settings, session=session, plugin_manager=plugin_manager
        ),
        registry=reg,
        agent_started_at=datetime.now(UTC),
        camera_service=CameraService(settings),
        pump_service=PumpService(settings),
    )
    event_bus = CommandEventBus()
    fake_sender = sender or FakeSender()
    dispatcher = CommandDispatcher(
        registry=reg,
        executor=CommandExecutor(),
        event_bus=event_bus,
        settings=settings,
        services=services,
        send=fake_sender.send,
        agent_version="0.1.0",
    )
    return dispatcher, fake_sender, event_bus


def _record_state(
    observed: list[CommandLifecycleState], state: CommandLifecycleState
) -> Callable[[CommandEvent], None]:
    def _listener(event: CommandEvent) -> None:
        observed.append(state)

    return _listener


def _command_envelope(command_type: str, arguments: Mapping[str, Any] | None = None) -> Envelope:
    return Envelope(
        protocol_version=1,
        message_type=MessageType.COMMAND,
        payload={
            "command_id": str(uuid4()),
            "command_type": command_type,
            "arguments": dict(arguments or {}),
        },
    )


@pytest.mark.asyncio
async def test_happy_path_sends_ack_then_result() -> None:
    """A valid command sends COMMAND_ACK, then COMMAND_RESULT with success=True."""
    registry = CommandRegistry()
    registry.register(_EchoHandler())
    dispatcher, sender, _bus = _make_dispatcher(registry=registry)
    envelope = _command_envelope("test.echo", {"x": 1})

    await dispatcher.handle_command(envelope)
    await asyncio.sleep(0.05)

    assert [message.message_type for message in sender.sent] == [
        MessageType.COMMAND_ACK,
        MessageType.COMMAND_RESULT,
    ]
    result_payload = CommandResultPayload.model_validate(sender.sent[1].payload)
    assert result_payload.success is True
    assert result_payload.result == {"x": 1}
    assert result_payload.error_message is None


@pytest.mark.asyncio
async def test_handler_not_found_sends_only_a_failed_result_no_ack() -> None:
    """An unregistered command_type sends COMMAND_RESULT(success=False) with no COMMAND_ACK."""
    dispatcher, sender, _bus = _make_dispatcher()
    envelope = _command_envelope("test.unknown")

    await dispatcher.handle_command(envelope)
    await asyncio.sleep(0.05)

    assert [message.message_type for message in sender.sent] == [MessageType.COMMAND_RESULT]
    result_payload = CommandResultPayload.model_validate(sender.sent[0].payload)
    assert result_payload.success is False
    assert "No handler registered" in (result_payload.error_message or "")


@pytest.mark.asyncio
async def test_validation_failure_sends_only_a_failed_result_no_ack() -> None:
    """A handler that rejects its arguments sends only a failed COMMAND_RESULT."""
    registry = CommandRegistry()
    registry.register(_RejectingHandler())
    dispatcher, sender, _bus = _make_dispatcher(registry=registry)
    envelope = _command_envelope("test.rejected")

    await dispatcher.handle_command(envelope)
    await asyncio.sleep(0.05)

    assert [message.message_type for message in sender.sent] == [MessageType.COMMAND_RESULT]
    result_payload = CommandResultPayload.model_validate(sender.sent[0].payload)
    assert result_payload.success is False
    assert "nope" in (result_payload.error_message or "")


@pytest.mark.asyncio
async def test_malformed_envelope_is_logged_and_ignored() -> None:
    """A COMMAND envelope that fails schema validation sends nothing and never raises."""
    dispatcher, sender, _bus = _make_dispatcher()
    envelope = Envelope(
        protocol_version=1, message_type=MessageType.COMMAND, payload={"not": "a command"}
    )

    await dispatcher.handle_command(envelope)
    await asyncio.sleep(0.02)

    assert sender.sent == []


@pytest.mark.asyncio
async def test_handle_command_returns_before_execution_completes() -> None:
    """handle_command() spawns processing as a task and returns immediately."""
    handler = _BlockingHandler()
    registry = CommandRegistry()
    registry.register(handler)
    dispatcher, sender, _bus = _make_dispatcher(registry=registry)
    envelope = _command_envelope("test.blocking")

    await dispatcher.handle_command(envelope)
    await asyncio.wait_for(handler.started.wait(), timeout=1)

    # The handler is mid-execution; only the ACK has been sent so far.
    assert [message.message_type for message in sender.sent] == [MessageType.COMMAND_ACK]

    handler.release.set()
    await asyncio.sleep(0.05)
    assert [message.message_type for message in sender.sent] == [
        MessageType.COMMAND_ACK,
        MessageType.COMMAND_RESULT,
    ]


@pytest.mark.asyncio
async def test_send_failure_is_caught_and_never_propagates() -> None:
    """If sending the ACK itself fails, _process's safety net logs it and does not raise."""
    registry = CommandRegistry()
    registry.register(_EchoHandler())
    sender = FakeSender()
    sender.fail_next = True
    dispatcher, _sender, _bus = _make_dispatcher(registry=registry, sender=sender)
    envelope = _command_envelope("test.echo")
    command_payload = CommandPayload.model_validate(envelope.payload)

    # Call the private pipeline directly (awaited, not spawned via
    # handle_command) so a re-raised exception would fail this test.
    await dispatcher._process(envelope, command_payload)


@pytest.mark.asyncio
async def test_lifecycle_events_fire_in_order_for_a_successful_command() -> None:
    """A successful command publishes VALIDATED, ACKNOWLEDGED, RUNNING, then COMPLETED."""
    registry = CommandRegistry()
    registry.register(_EchoHandler())
    dispatcher, _sender, bus = _make_dispatcher(registry=registry)
    observed: list[CommandLifecycleState] = []
    for state in CommandLifecycleState:
        bus.subscribe(state, _record_state(observed, state))

    envelope = _command_envelope("test.echo")
    await dispatcher.handle_command(envelope)
    await asyncio.sleep(0.05)

    assert observed == [
        CommandLifecycleState.VALIDATED,
        CommandLifecycleState.ACKNOWLEDGED,
        CommandLifecycleState.RUNNING,
        CommandLifecycleState.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_lifecycle_events_stop_at_failed_for_handler_not_found() -> None:
    """A handler-not-found command publishes exactly one event: FAILED."""
    dispatcher, _sender, bus = _make_dispatcher()
    observed: list[CommandLifecycleState] = []
    for state in CommandLifecycleState:
        bus.subscribe(state, _record_state(observed, state))

    await dispatcher.handle_command(_command_envelope("test.missing"))
    await asyncio.sleep(0.02)

    assert observed == [CommandLifecycleState.FAILED]


@pytest.mark.asyncio
async def test_aclose_cancels_in_flight_tasks() -> None:
    """aclose() cancels any command-processing task still running."""
    handler = _BlockingHandler()
    registry = CommandRegistry()
    registry.register(handler)
    dispatcher, _sender, _bus = _make_dispatcher(registry=registry)

    await dispatcher.handle_command(_command_envelope("test.blocking"))
    await asyncio.wait_for(handler.started.wait(), timeout=1)

    await dispatcher.aclose()

    assert dispatcher._tasks == set()


@pytest.mark.asyncio
async def test_aclose_with_no_tasks_is_a_no_op() -> None:
    """aclose() with nothing in flight doesn't raise."""
    dispatcher, _sender, _bus = _make_dispatcher()
    await dispatcher.aclose()
