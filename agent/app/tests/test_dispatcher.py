"""Tests for the message dispatcher's routing table."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.dispatcher.dispatcher import MessageDispatcher
from shared.protocol.message_types import MessageType
from shared.protocol.schemas import Envelope


def _envelope(message_type: MessageType) -> Envelope:
    return Envelope(protocol_version=1, message_type=message_type, payload={})


@pytest.mark.asyncio
async def test_dispatch_invokes_registered_handler() -> None:
    """A registered handler is invoked with the envelope."""
    dispatcher = MessageDispatcher()
    received: list[Envelope] = []

    async def handler(envelope: Envelope) -> None:
        received.append(envelope)

    dispatcher.register(MessageType.PING, handler)
    envelope = _envelope(MessageType.PING)

    await dispatcher.dispatch(envelope)

    assert received == [envelope]


@pytest.mark.asyncio
async def test_dispatch_ignores_unregistered_message_type() -> None:
    """An unregistered message type (e.g. COMMAND) is ignored, not raised."""
    dispatcher = MessageDispatcher()

    await dispatcher.dispatch(_envelope(MessageType.COMMAND))


@pytest.mark.asyncio
async def test_register_replaces_existing_handler() -> None:
    """Registering twice for the same type replaces the earlier handler."""
    dispatcher = MessageDispatcher()
    calls: list[str] = []

    async def first(_: Envelope) -> None:
        calls.append("first")

    async def second(_: Envelope) -> None:
        calls.append("second")

    dispatcher.register(MessageType.PONG, first)
    dispatcher.register(MessageType.PONG, second)

    await dispatcher.dispatch(_envelope(MessageType.PONG))

    assert calls == ["second"]


def test_envelope_helper_has_a_timestamp() -> None:
    """Sanity check that the shared Envelope default_factory produces a real timestamp."""
    envelope = _envelope(MessageType.ERROR)
    assert envelope.timestamp <= datetime.now(UTC)
