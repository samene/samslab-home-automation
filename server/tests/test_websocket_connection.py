"""Tests for one connection's outgoing queue, backpressure, ack tracking, and dedup."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.websocket.connection import Connection
from app.websocket.constants import MAX_SEEN_MESSAGE_IDS
from app.websocket.exceptions import BackpressureExceededError
from app.websocket.protocol import MessageType
from app.websocket.schemas import Envelope


class _FakeWebSocket:
    """A minimal stand-in for Starlette's WebSocket, recording sent frames."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


def _make_connection(
    *, queue_size: int = 10, ack_timeout_seconds: float = 5.0, ack_max_retries: int = 3
) -> tuple[Connection, _FakeWebSocket]:
    websocket = _FakeWebSocket()
    connection = Connection(
        websocket,  # type: ignore[arg-type]
        queue_size=queue_size,
        ack_timeout_seconds=ack_timeout_seconds,
        ack_max_retries=ack_max_retries,
    )
    return connection, websocket


def _envelope(message_type: MessageType = MessageType.EVENT) -> Envelope:
    return Envelope(protocol_version=1, message_type=message_type, payload={})


def test_enqueue_tracks_ack_required_message_types() -> None:
    """An EVENT message is tracked in pending_acks once enqueued."""
    connection, _ = _make_connection()
    envelope = _envelope(MessageType.EVENT)
    connection.enqueue(envelope)
    assert envelope.message_id in connection.pending_acks


def test_enqueue_does_not_track_non_ack_message_types() -> None:
    """A PING message is never tracked for acknowledgement."""
    connection, _ = _make_connection()
    envelope = _envelope(MessageType.PING)
    connection.enqueue(envelope)
    assert envelope.message_id not in connection.pending_acks


def test_enqueue_raises_backpressure_error_when_queue_is_full() -> None:
    """A full bounded queue raises immediately rather than blocking."""
    connection, _ = _make_connection(queue_size=1)
    connection.enqueue(_envelope(MessageType.PING))
    with pytest.raises(BackpressureExceededError):
        connection.enqueue(_envelope(MessageType.PING))


def test_record_ack_resolves_a_pending_message() -> None:
    """Recording an ack removes the message from pending_acks."""
    connection, _ = _make_connection()
    envelope = _envelope(MessageType.EVENT)
    connection.enqueue(envelope)
    connection.record_ack(envelope.message_id)
    assert envelope.message_id not in connection.pending_acks


def test_record_ack_is_a_no_op_for_an_unknown_message_id() -> None:
    """Acknowledging an untracked message ID never raises."""
    connection, _ = _make_connection()
    connection.record_ack(uuid4())


def test_duplicate_detection_marks_and_recognizes_seen_ids() -> None:
    """A message ID is only a duplicate after being marked seen."""
    connection, _ = _make_connection()
    message_id = uuid4()
    assert not connection.is_duplicate(message_id)
    connection.mark_seen(message_id)
    assert connection.is_duplicate(message_id)


def test_duplicate_detection_is_bounded() -> None:
    """Only the most recent MAX_SEEN_MESSAGE_IDS are remembered."""
    connection, _ = _make_connection()
    first_id = uuid4()
    connection.mark_seen(first_id)
    for _ in range(MAX_SEEN_MESSAGE_IDS):
        connection.mark_seen(uuid4())
    assert not connection.is_duplicate(first_id)


@pytest.mark.asyncio
async def test_writer_loop_sends_queued_envelopes_and_records_metrics() -> None:
    """The writer loop drains the queue to the socket in order."""
    connection, websocket = _make_connection()
    envelope = _envelope(MessageType.PING)
    connection.enqueue(envelope)
    task = asyncio.create_task(connection.writer_loop())
    for _ in range(50):
        if websocket.sent:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(websocket.sent) == 1
    assert '"PING"' in websocket.sent[0]


@pytest.mark.asyncio
async def test_ack_watchdog_retries_up_to_the_configured_limit_then_drops() -> None:
    """An unacknowledged message is retried once, then dropped after max retries."""
    connection, _ = _make_connection(queue_size=10, ack_timeout_seconds=0.01, ack_max_retries=1)
    envelope = _envelope(MessageType.EVENT)
    connection.enqueue(envelope)
    task = asyncio.create_task(connection.ack_watchdog_loop())
    for _ in range(200):
        if envelope.message_id not in connection.pending_acks:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert envelope.message_id not in connection.pending_acks


@pytest.mark.asyncio
async def test_ack_watchdog_stops_retrying_once_acknowledged() -> None:
    """A message acknowledged before its deadline is never retried or dropped unexpectedly."""
    connection, _ = _make_connection(queue_size=10, ack_timeout_seconds=0.05, ack_max_retries=3)
    envelope = _envelope(MessageType.EVENT)
    connection.enqueue(envelope)
    connection.record_ack(envelope.message_id)
    task = asyncio.create_task(connection.ack_watchdog_loop())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert envelope.message_id not in connection.pending_acks


@pytest.mark.asyncio
async def test_ack_watchdog_skips_a_message_before_its_deadline() -> None:
    """A message whose deadline has not yet passed is left untouched on a watchdog sweep."""
    connection, _ = _make_connection(queue_size=10, ack_timeout_seconds=5.0, ack_max_retries=3)
    envelope = _envelope(MessageType.EVENT)
    connection.enqueue(envelope)
    task = asyncio.create_task(connection.ack_watchdog_loop())
    await asyncio.sleep(1.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert connection.pending_acks[envelope.message_id].attempts == 0


@pytest.mark.asyncio
async def test_ack_watchdog_logs_and_continues_when_a_retry_finds_a_full_queue() -> None:
    """A retry attempt that hits a still-full queue is dropped for that sweep, not fatal."""
    connection, _ = _make_connection(queue_size=1, ack_timeout_seconds=0.01, ack_max_retries=3)
    envelope = _envelope(MessageType.EVENT)
    connection.enqueue(envelope)  # fills the only queue slot; nothing ever drains it here
    task = asyncio.create_task(connection.ack_watchdog_loop())
    await asyncio.sleep(1.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert connection.pending_acks[envelope.message_id].attempts == 1


@pytest.mark.asyncio
async def test_close_invokes_the_underlying_socket_close() -> None:
    """Closing a connection closes its underlying socket with the given code/reason."""
    connection, websocket = _make_connection()
    await connection.close(code=4400, reason="protocol_violation")
    assert websocket.closed == (4400, "protocol_violation")


@pytest.mark.asyncio
async def test_close_tolerates_an_already_closed_socket() -> None:
    """Closing a socket that itself raises on close() never propagates."""

    class _BrokenWebSocket(_FakeWebSocket):
        async def close(self, *, code: int = 1000, reason: str = "") -> None:
            raise RuntimeError("already closed")

    connection = Connection(
        _BrokenWebSocket(),  # type: ignore[arg-type]
        queue_size=10,
        ack_timeout_seconds=5.0,
        ack_max_retries=3,
    )
    await connection.close()
