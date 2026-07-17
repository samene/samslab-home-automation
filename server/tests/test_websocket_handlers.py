"""Tests for dispatch_message: generic, business-logic-free per-type handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domains.auth.schemas import Principal, PrincipalType
from app.websocket.exceptions import ProtocolViolationError
from app.websocket.handlers import dispatch_message
from app.websocket.protocol import MessageType
from app.websocket.schemas import Envelope, MessageAckPayload
from app.websocket.session import ConnectionState, Session


class _FakeConnection:
    def __init__(self) -> None:
        self.enqueued: list[Envelope] = []
        self.acked: list[object] = []

    def enqueue(self, envelope: Envelope) -> None:
        self.enqueued.append(envelope)

    def record_ack(self, message_id: object) -> None:
        self.acked.append(message_id)


def _make_session(*, last_seen: datetime | None = None) -> Session:
    now = last_seen or (datetime.now(UTC) - timedelta(hours=1))
    return Session(
        device_id=uuid4(),
        connection_id=uuid4(),
        connected_at=now,
        last_seen=now,
        protocol_version=1,
        authenticated_principal=Principal(
            principal_type=PrincipalType.DEVICE, subject_id="dev", device_id=uuid4()
        ),
        connection=_FakeConnection(),  # type: ignore[arg-type]
        connection_state=ConnectionState.OPEN,
    )


def _envelope(message_type: MessageType, payload: dict[str, object] | None = None) -> Envelope:
    return Envelope(protocol_version=1, message_type=message_type, payload=payload or {})


@pytest.mark.asyncio
async def test_dispatch_always_advances_last_seen() -> None:
    """Every dispatched message updates the session's liveness timestamp."""
    session = _make_session()
    stale_last_seen = session.last_seen
    await dispatch_message(
        session=session,
        connection=session.connection,
        envelope=_envelope(MessageType.PONG),
    )
    assert session.last_seen > stale_last_seen


@pytest.mark.asyncio
async def test_ping_receives_a_pong_reply_with_correlation_id() -> None:
    """A PING is answered with a PONG correlated to the original message."""
    session = _make_session()
    envelope = _envelope(MessageType.PING)
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    sent = session.connection.enqueued  # type: ignore[attr-defined]
    assert len(sent) == 1
    assert sent[0].message_type is MessageType.PONG
    assert sent[0].correlation_id == envelope.message_id


@pytest.mark.asyncio
async def test_pong_sends_no_reply() -> None:
    """A PONG is accepted silently; it never triggers an outgoing message."""
    session = _make_session()
    await dispatch_message(
        session=session,
        connection=session.connection,
        envelope=_envelope(MessageType.PONG),
    )
    assert session.connection.enqueued == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_message_ack_resolves_the_pending_outgoing_message() -> None:
    """A MESSAGE_ACK payload is forwarded to the connection's record_ack."""
    session = _make_session()
    acknowledged_id = uuid4()
    envelope = _envelope(MessageType.MESSAGE_ACK, {"acknowledged_message_id": str(acknowledged_id)})
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    assert session.connection.acked == [acknowledged_id]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_message_ack_with_a_malformed_payload_raises_protocol_violation() -> None:
    """A MESSAGE_ACK missing its required field is a protocol violation, not a crash."""
    session = _make_session()
    envelope = _envelope(MessageType.MESSAGE_ACK, {})
    with pytest.raises(ProtocolViolationError):
        await dispatch_message(
            session=session,
            connection=session.connection,
            envelope=envelope,
        )


@pytest.mark.asyncio
async def test_error_message_is_accepted_without_raising() -> None:
    """An ERROR message from the agent is logged, not treated as fatal."""
    session = _make_session()
    envelope = _envelope(MessageType.ERROR, {"code": "bad_state", "message": "oops"})
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    assert session.connection.enqueued == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "message_type",
    [MessageType.COMMAND, MessageType.EVENT, MessageType.LOG],
)
@pytest.mark.asyncio
async def test_business_message_types_receive_a_generic_message_ack(
    message_type: MessageType,
) -> None:
    """COMMAND/EVENT/LOG-family messages are acknowledged generically, never dispatched further."""
    session = _make_session()
    envelope = _envelope(
        message_type, {"anything": "goes"} if message_type is MessageType.EVENT else {}
    )
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    sent = session.connection.enqueued  # type: ignore[attr-defined]
    assert len(sent) == 1
    assert sent[0].message_type is MessageType.MESSAGE_ACK
    ack_payload = MessageAckPayload.model_validate(sent[0].payload)
    assert ack_payload.acknowledged_message_id == envelope.message_id


@pytest.mark.asyncio
async def test_command_ack_is_acknowledged_and_published_when_a_bus_is_given() -> None:
    """A COMMAND_ACK is generically acked and published as CommandAckReceived."""
    session = _make_session()
    command_id = uuid4()
    envelope = _envelope(MessageType.COMMAND_ACK, {"command_id": str(command_id)})
    published: list[object] = []

    class _FakeBus:
        async def publish(self, event: object) -> None:
            published.append(event)

    await dispatch_message(
        session=session,
        connection=session.connection,
        envelope=envelope,
        event_bus=_FakeBus(),  # type: ignore[arg-type]
    )
    sent = session.connection.enqueued  # type: ignore[attr-defined]
    assert len(sent) == 1
    assert sent[0].message_type is MessageType.MESSAGE_ACK
    assert len(published) == 1
    assert published[0].command_id == command_id  # type: ignore[attr-defined]
    assert published[0].device_id == session.device_id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_command_ack_without_a_bus_still_sends_the_generic_ack() -> None:
    """A COMMAND_ACK is still acknowledged even when no event bus is configured."""
    session = _make_session()
    envelope = _envelope(MessageType.COMMAND_ACK, {"command_id": str(uuid4())})
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    sent = session.connection.enqueued  # type: ignore[attr-defined]
    assert len(sent) == 1
    assert sent[0].message_type is MessageType.MESSAGE_ACK


@pytest.mark.asyncio
async def test_command_ack_resolves_the_original_commands_pending_ack() -> None:
    """A COMMAND_ACK's correlation_id (the original COMMAND envelope's message_id,
    per the agent's _send_ack) must resolve that envelope's own transport-level
    pending-ack — otherwise Connection.ack_watchdog_loop keeps resending the
    COMMAND even though the device already handled it (see handlers.py)."""
    session = _make_session()
    original_message_id = uuid4()
    envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.COMMAND_ACK,
        payload={"command_id": str(uuid4())},
        correlation_id=original_message_id,
    )
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    acked = session.connection.acked  # type: ignore[attr-defined]
    assert acked == [original_message_id]


@pytest.mark.asyncio
async def test_command_ack_with_a_malformed_payload_raises_protocol_violation() -> None:
    """A COMMAND_ACK missing its required command_id is a protocol violation."""
    session = _make_session()
    envelope = _envelope(MessageType.COMMAND_ACK, {})
    with pytest.raises(ProtocolViolationError):
        await dispatch_message(session=session, connection=session.connection, envelope=envelope)


@pytest.mark.asyncio
async def test_command_result_is_acknowledged_and_published_when_a_bus_is_given() -> None:
    """A COMMAND_RESULT is generically acked and published as CommandResultReceived."""
    session = _make_session()
    command_id = uuid4()
    envelope = _envelope(
        MessageType.COMMAND_RESULT,
        {"command_id": str(command_id), "success": True, "result": {"ok": True}},
    )
    published: list[object] = []

    class _FakeBus:
        async def publish(self, event: object) -> None:
            published.append(event)

    await dispatch_message(
        session=session,
        connection=session.connection,
        envelope=envelope,
        event_bus=_FakeBus(),  # type: ignore[arg-type]
    )
    sent = session.connection.enqueued  # type: ignore[attr-defined]
    assert len(sent) == 1
    assert sent[0].message_type is MessageType.MESSAGE_ACK
    assert len(published) == 1
    assert published[0].command_id == command_id  # type: ignore[attr-defined]
    assert published[0].success is True  # type: ignore[attr-defined]
    assert published[0].result == {"ok": True}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_command_result_resolves_the_original_commands_pending_ack() -> None:
    """Same reasoning as COMMAND_ACK: a COMMAND_RESULT's correlation_id must also
    resolve the original COMMAND's pending-ack, in case the COMMAND_ACK was missed."""
    session = _make_session()
    original_message_id = uuid4()
    envelope = Envelope(
        protocol_version=1,
        message_type=MessageType.COMMAND_RESULT,
        payload={"command_id": str(uuid4()), "success": True, "result": {}},
        correlation_id=original_message_id,
    )
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    acked = session.connection.acked  # type: ignore[attr-defined]
    assert acked == [original_message_id]


@pytest.mark.asyncio
async def test_command_result_with_a_malformed_payload_raises_protocol_violation() -> None:
    """A COMMAND_RESULT missing its required fields is a protocol violation."""
    session = _make_session()
    envelope = _envelope(MessageType.COMMAND_RESULT, {})
    with pytest.raises(ProtocolViolationError):
        await dispatch_message(session=session, connection=session.connection, envelope=envelope)


@pytest.mark.asyncio
async def test_an_unexpected_message_type_is_logged_but_not_fatal() -> None:
    """A WELCOME received from an agent (server-only in practice) is logged, not raised."""
    session = _make_session()
    envelope = _envelope(MessageType.WELCOME, {})
    await dispatch_message(session=session, connection=session.connection, envelope=envelope)
    assert session.connection.enqueued == []  # type: ignore[attr-defined]
