"""End-to-end test: the transport-level MessageDispatcher handing COMMAND off to the
command runtime, exactly as ``app/lifecycle/orchestrator.py`` wires it in production.

Proves "the transport layer should remain unaware of execution details": the
``MessageDispatcher`` here only ever sees ``Envelope`` in, nothing out — it
never calls into the executor/registry/context directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.commands.builtin import register_builtin_handlers
from app.commands.context import CommandServices
from app.commands.dispatcher import CommandDispatcher
from app.commands.events import CommandEventBus
from app.commands.executor import CommandExecutor
from app.commands.registry import CommandRegistry
from app.dispatcher.dispatcher import MessageDispatcher
from app.health.service import HealthService
from app.plugins.camera.service import CameraService
from app.plugins.registry import PluginManager
from app.services.session import SessionState
from app.tests.conftest import make_settings
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import CommandResultPayload, Envelope
from shared.protocol.serializer import deserialize, serialize


class RecordingSender:
    """Stands in for ``ConnectionManager.send`` — records serialized wire envelopes."""

    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def send(self, envelope: Envelope) -> None:
        # Round-trip through the real serializer, exactly like a live connection would.
        self.sent.append(deserialize(serialize(envelope)))


@pytest.mark.asyncio
async def test_command_flows_from_message_dispatcher_through_to_result() -> None:
    """A COMMAND handed to MessageDispatcher.dispatch() produces ACK then RESULT."""
    settings = make_settings()
    plugin_manager = PluginManager()
    session = SessionState()
    registry = CommandRegistry()
    register_builtin_handlers(registry)
    sender = RecordingSender()

    command_dispatcher = CommandDispatcher(
        registry=registry,
        executor=CommandExecutor(),
        event_bus=CommandEventBus(),
        settings=settings,
        services=CommandServices(
            plugin_manager=plugin_manager,
            health_service=HealthService(
                settings=settings, session=session, plugin_manager=plugin_manager
            ),
            registry=registry,
            agent_started_at=datetime.now(UTC),
            camera_service=CameraService(settings),
        ),
        send=sender.send,
        agent_version="0.1.0",
    )

    message_dispatcher = MessageDispatcher()
    message_dispatcher.register(MessageType.COMMAND, command_dispatcher.handle_command)

    incoming = Envelope(
        protocol_version=1,
        message_type=MessageType.COMMAND,
        payload={
            "command_id": str(uuid4()),
            "command_type": "system.echo",
            "arguments": {"greeting": "hello"},
        },
    )

    # This is exactly what Agent._receive_loop() does with a real envelope.
    await message_dispatcher.dispatch(incoming)
    await asyncio.sleep(0.05)

    assert [envelope.message_type for envelope in sender.sent] == [
        MessageType.COMMAND_ACK,
        MessageType.COMMAND_RESULT,
    ]
    result = CommandResultPayload.model_validate(sender.sent[1].payload)
    assert result.success is True
    assert result.result == {"greeting": "hello"}


@pytest.mark.asyncio
async def test_message_dispatcher_never_blocks_on_command_execution() -> None:
    """dispatch() for a COMMAND returns promptly even while the handler is still running."""
    settings = make_settings()
    plugin_manager = PluginManager()
    session = SessionState()
    registry = CommandRegistry()
    register_builtin_handlers(registry)
    sender = RecordingSender()

    command_dispatcher = CommandDispatcher(
        registry=registry,
        executor=CommandExecutor(),
        event_bus=CommandEventBus(),
        settings=settings,
        services=CommandServices(
            plugin_manager=plugin_manager,
            health_service=HealthService(
                settings=settings, session=session, plugin_manager=plugin_manager
            ),
            registry=registry,
            agent_started_at=datetime.now(UTC),
            camera_service=CameraService(settings),
        ),
        send=sender.send,
        agent_version="0.1.0",
    )
    message_dispatcher = MessageDispatcher()
    message_dispatcher.register(MessageType.COMMAND, command_dispatcher.handle_command)

    incoming = Envelope(
        protocol_version=1,
        message_type=MessageType.COMMAND,
        payload={"command_id": str(uuid4()), "command_type": "system.ping", "arguments": {}},
    )

    await asyncio.wait_for(message_dispatcher.dispatch(incoming), timeout=0.5)

    await command_dispatcher.aclose()
