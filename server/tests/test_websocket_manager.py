"""Tests for the in-memory SessionManager: one session per device, send, broadcast, disconnect."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domains.auth.schemas import Principal, PrincipalType
from app.websocket.exceptions import BackpressureExceededError, DuplicateSessionError
from app.websocket.manager import SessionManager
from app.websocket.protocol import MessageType
from app.websocket.schemas import Envelope
from app.websocket.session import ConnectionState, Session


class _FakeConnection:
    """A minimal stand-in for Connection, recording enqueued/closed activity."""

    def __init__(self, *, fail_enqueue: bool = False) -> None:
        self.enqueued: list[Envelope] = []
        self.closed: tuple[int, str] | None = None
        self.pending_acks: dict[object, object] = {}
        self._fail_enqueue = fail_enqueue

    def enqueue(self, envelope: Envelope) -> None:
        if self._fail_enqueue:
            raise BackpressureExceededError("full")
        self.enqueued.append(envelope)

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


def _make_session(*, device_id: UUID | None = None, fail_enqueue: bool = False) -> Session:
    now = datetime.now(UTC)
    return Session(
        device_id=device_id or uuid4(),
        connection_id=uuid4(),
        connected_at=now,
        last_seen=now,
        protocol_version=1,
        authenticated_principal=Principal(
            principal_type=PrincipalType.DEVICE, subject_id="dev", device_id=uuid4()
        ),
        connection=_FakeConnection(fail_enqueue=fail_enqueue),  # type: ignore[arg-type]
        connection_state=ConnectionState.OPEN,
    )


def _envelope() -> Envelope:
    return Envelope(protocol_version=1, message_type=MessageType.EVENT, payload={})


@pytest.mark.asyncio
async def test_register_and_get_round_trip() -> None:
    """A registered session is retrievable by its device_id."""
    manager = SessionManager()
    session = _make_session()
    await manager.register(session)
    assert manager.get(session.device_id) is session


@pytest.mark.asyncio
async def test_register_rejects_a_second_open_session_for_the_same_device() -> None:
    """A device already holding an OPEN session cannot register a second one."""
    manager = SessionManager()
    device_id = uuid4()
    await manager.register(_make_session(device_id=device_id))
    with pytest.raises(DuplicateSessionError):
        await manager.register(_make_session(device_id=device_id))


@pytest.mark.asyncio
async def test_register_allows_replacing_a_closed_session() -> None:
    """A device whose prior session is CLOSED may register a fresh one."""
    manager = SessionManager()
    device_id = uuid4()
    stale = _make_session(device_id=device_id)
    stale.connection_state = ConnectionState.CLOSED
    await manager.register(stale)
    fresh = _make_session(device_id=device_id)
    await manager.register(fresh)
    assert manager.get(device_id) is fresh


@pytest.mark.asyncio
async def test_unregister_removes_a_tracked_session() -> None:
    """Unregistering a device removes it from the registry."""
    manager = SessionManager()
    session = _make_session()
    await manager.register(session)
    await manager.unregister(session.device_id)
    assert manager.get(session.device_id) is None


@pytest.mark.asyncio
async def test_unregister_is_a_no_op_for_an_unknown_device() -> None:
    """Unregistering a device with no session never raises."""
    manager = SessionManager()
    await manager.unregister(uuid4())


@pytest.mark.asyncio
async def test_list_sessions_returns_a_summary_for_every_tracked_session() -> None:
    """Listing sessions returns one summary DTO per registered device."""
    manager = SessionManager()
    first = _make_session()
    second = _make_session()
    await manager.register(first)
    await manager.register(second)
    summaries = manager.list_sessions()
    assert {summary.device_id for summary in summaries} == {first.device_id, second.device_id}


@pytest.mark.asyncio
async def test_get_summary_returns_none_for_an_unconnected_device() -> None:
    """Looking up a summary for a device with no session returns None."""
    manager = SessionManager()
    assert manager.get_summary(uuid4()) is None


@pytest.mark.asyncio
async def test_get_summary_reflects_pending_message_count() -> None:
    """The summary's pending_message_count mirrors the connection's pending acks."""
    manager = SessionManager()
    session = _make_session()
    session.connection.pending_acks[uuid4()] = object()  # type: ignore[assignment]
    await manager.register(session)
    summary = manager.get_summary(session.device_id)
    assert summary is not None
    assert summary.pending_message_count == 1


def test_send_queues_a_message_for_a_connected_device() -> None:
    """Sending to a connected device enqueues the envelope on its connection."""
    manager = SessionManager()
    session = _make_session()
    manager._sessions[session.device_id] = session  # noqa: SLF001 - direct registry seed for a sync test
    envelope = _envelope()
    assert manager.send(session.device_id, envelope) is True
    assert session.connection.enqueued == [envelope]  # type: ignore[attr-defined]


def test_send_returns_false_for_a_disconnected_device() -> None:
    """Sending to a device with no session returns False rather than raising."""
    manager = SessionManager()
    assert manager.send(uuid4(), _envelope()) is False


def test_broadcast_delivers_to_every_session_except_excluded() -> None:
    """Broadcast reaches every connected device except the excluded one."""
    manager = SessionManager()
    included = _make_session()
    excluded = _make_session()
    manager._sessions[included.device_id] = included  # noqa: SLF001
    manager._sessions[excluded.device_id] = excluded  # noqa: SLF001
    count = manager.broadcast(_envelope(), exclude=excluded.device_id)
    assert count == 1
    assert included.connection.enqueued  # type: ignore[attr-defined]
    assert not excluded.connection.enqueued  # type: ignore[attr-defined]


def test_broadcast_skips_a_session_whose_queue_is_full() -> None:
    """A single backpressured session is skipped, not fatal to the whole broadcast."""
    manager = SessionManager()
    healthy = _make_session()
    full = _make_session(fail_enqueue=True)
    manager._sessions[healthy.device_id] = healthy  # noqa: SLF001
    manager._sessions[full.device_id] = full  # noqa: SLF001
    count = manager.broadcast(_envelope())
    assert count == 1


@pytest.mark.asyncio
async def test_disconnect_closes_and_forgets_a_session() -> None:
    """Disconnecting a device closes its connection and removes it from the registry."""
    manager = SessionManager()
    session = _make_session()
    await manager.register(session)
    await manager.disconnect(session.device_id, code=4400, reason="protocol_violation")
    assert manager.get(session.device_id) is None
    assert session.connection.closed == (4400, "protocol_violation")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_disconnect_is_a_no_op_for_an_unknown_device() -> None:
    """Disconnecting an unknown device never raises."""
    manager = SessionManager()
    await manager.disconnect(uuid4())


@pytest.mark.asyncio
async def test_close_all_disconnects_every_registered_session() -> None:
    """close_all clears the entire registry, closing each connection."""
    manager = SessionManager()
    first = _make_session()
    second = _make_session()
    await manager.register(first)
    await manager.register(second)
    await manager.close_all()
    assert manager.list_sessions() == []
    assert first.connection.closed is not None  # type: ignore[attr-defined]
    assert second.connection.closed is not None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_track_removes_the_task_from_active_count_once_it_finishes() -> None:
    """A tracked task that finishes on its own drops active_task_count back to zero."""
    manager = SessionManager()

    async def _quick() -> None:
        await asyncio.sleep(0.01)

    task = asyncio.create_task(_quick())
    manager.track(task)
    assert manager.active_task_count == 1
    await task
    await asyncio.sleep(0.01)  # let the done-callback run
    assert manager.active_task_count == 0


@pytest.mark.asyncio
async def test_wait_closed_is_a_no_op_with_no_tracked_tasks() -> None:
    """Waiting with nothing tracked returns immediately."""
    manager = SessionManager()
    await manager.wait_closed(timeout=1.0)


@pytest.mark.asyncio
async def test_wait_closed_cancels_a_task_that_outlives_the_timeout() -> None:
    """A tracked task still running past the timeout is forcibly cancelled."""
    manager = SessionManager()

    async def _forever() -> None:
        await asyncio.sleep(100)

    task = asyncio.create_task(_forever())
    manager.track(task)
    await manager.wait_closed(timeout=0.05)
    await asyncio.sleep(0.01)
    assert task.cancelled() or task.done()
