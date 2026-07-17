"""Tests for DeliveryService: connectivity checks and sending a COMMAND envelope."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.dispatcher.delivery import DeliveryService
from app.dispatcher.exceptions import DeliveryFailedError
from app.dispatcher.queue import QueuedCommand
from app.domains.commands.models import CommandPriority
from app.websocket.exceptions import BackpressureExceededError
from app.websocket.protocol import MessageType
from app.websocket.schemas import CommandPayload, Envelope
from app.websocket.session import ConnectionState


class _FakeSession:
    def __init__(self, *, state: ConnectionState = ConnectionState.OPEN) -> None:
        self.connection_state = state


class _FakeSessionManager:
    def __init__(self) -> None:
        self.sessions: dict[UUID, _FakeSession] = {}
        self.sent: list[tuple[UUID, Envelope]] = []
        self._raise_backpressure = False

    def get(self, device_id: UUID) -> _FakeSession | None:
        return self.sessions.get(device_id)

    def send(self, device_id: UUID, envelope: Envelope) -> bool:
        if self._raise_backpressure:
            raise BackpressureExceededError("full")
        if device_id not in self.sessions:
            return False
        self.sent.append((device_id, envelope))
        return True


def _item(device_id: UUID) -> QueuedCommand:
    return QueuedCommand(
        command_id=uuid4(),
        device_id=device_id,
        priority=CommandPriority.NORMAL,
        command_type="pump.start",
        payload={"duration_s": 5},
        enqueued_at=datetime.now(UTC),
    )


def test_is_device_connected_true_for_an_open_session() -> None:
    """A device with an OPEN session is considered connected."""
    device_id = uuid4()
    session_manager = _FakeSessionManager()
    session_manager.sessions[device_id] = _FakeSession(state=ConnectionState.OPEN)
    delivery = DeliveryService(session_manager=session_manager)  # type: ignore[arg-type]
    assert delivery.is_device_connected(device_id) is True


def test_is_device_connected_false_for_no_session() -> None:
    """A device with no session at all is not connected."""
    delivery = DeliveryService(session_manager=_FakeSessionManager())  # type: ignore[arg-type]
    assert delivery.is_device_connected(uuid4()) is False


def test_is_device_connected_false_for_a_non_open_session() -> None:
    """A session that exists but isn't OPEN (closing/closed) is not usable for delivery."""
    device_id = uuid4()
    session_manager = _FakeSessionManager()
    session_manager.sessions[device_id] = _FakeSession(state=ConnectionState.CLOSING)
    delivery = DeliveryService(session_manager=session_manager)  # type: ignore[arg-type]
    assert delivery.is_device_connected(device_id) is False


@pytest.mark.asyncio
async def test_send_command_builds_a_correct_command_envelope() -> None:
    """The envelope sent carries the command's id, type, and payload as arguments."""
    device_id = uuid4()
    session_manager = _FakeSessionManager()
    session_manager.sessions[device_id] = _FakeSession()
    delivery = DeliveryService(session_manager=session_manager)  # type: ignore[arg-type]
    item = _item(device_id)

    sent = await delivery.send_command(item)

    assert sent is True
    assert len(session_manager.sent) == 1
    sent_device_id, envelope = session_manager.sent[0]
    assert sent_device_id == device_id
    assert envelope.message_type is MessageType.COMMAND
    payload = CommandPayload.model_validate(envelope.payload)
    assert payload.command_id == item.command_id
    assert payload.command_type == item.command_type
    assert payload.arguments == item.payload


@pytest.mark.asyncio
async def test_send_command_returns_false_when_device_not_connected() -> None:
    """Sending to a device with no session returns False rather than raising."""
    delivery = DeliveryService(session_manager=_FakeSessionManager())  # type: ignore[arg-type]
    sent = await delivery.send_command(_item(uuid4()))
    assert sent is False


@pytest.mark.asyncio
async def test_send_command_raises_delivery_failed_on_backpressure() -> None:
    """A connected device whose queue is full raises DeliveryFailedError, distinct from 'not sent'."""
    device_id = uuid4()
    session_manager = _FakeSessionManager()
    session_manager.sessions[device_id] = _FakeSession()
    session_manager._raise_backpressure = True
    delivery = DeliveryService(session_manager=session_manager)  # type: ignore[arg-type]
    with pytest.raises(DeliveryFailedError):
        await delivery.send_command(_item(device_id))
