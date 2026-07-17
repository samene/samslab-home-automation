"""Tests for HeartbeatMonitor's PING/PONG liveness and idle-timeout enforcement."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domains.auth.schemas import Principal, PrincipalType
from app.websocket.heartbeat import HeartbeatMonitor, build_ping_envelope
from app.websocket.protocol import MessageType
from app.websocket.session import ConnectionState, Session


class _FakeConnection:
    def __init__(self) -> None:
        self.enqueued: list[object] = []

    def enqueue(self, envelope: object) -> None:
        self.enqueued.append(envelope)


def _make_session() -> Session:
    now = datetime.now(UTC)
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


def test_build_ping_envelope_has_the_expected_type_and_version() -> None:
    """A built PING envelope carries the requested protocol version."""
    envelope = build_ping_envelope(1)
    assert envelope.message_type is MessageType.PING
    assert envelope.protocol_version == 1


@pytest.mark.asyncio
async def test_idle_timeout_fires_when_nothing_is_heard() -> None:
    """An idle_timeout shorter than the poll interval trips on the first cycle."""
    session = _make_session()
    calls: list[tuple[Session, str]] = []

    async def on_timeout(session: Session, reason: str) -> None:
        calls.append((session, reason))

    monitor = HeartbeatMonitor(
        session,
        session.connection,
        interval_seconds=0.02,
        heartbeat_timeout_seconds=1.0,
        idle_timeout_seconds=0.001,
        on_timeout=on_timeout,
    )
    await asyncio.wait_for(monitor.run(), timeout=2.0)
    assert len(calls) == 1
    assert calls[0][1] == "idle_timeout"


@pytest.mark.asyncio
async def test_heartbeat_timeout_fires_when_no_reply_updates_last_seen() -> None:
    """A PING with no corresponding activity trips a heartbeat_timeout."""
    session = _make_session()
    calls: list[tuple[Session, str]] = []

    async def on_timeout(session: Session, reason: str) -> None:
        calls.append((session, reason))

    monitor = HeartbeatMonitor(
        session,
        session.connection,
        interval_seconds=0.01,
        heartbeat_timeout_seconds=0.01,
        idle_timeout_seconds=10.0,
        on_timeout=on_timeout,
    )
    await asyncio.wait_for(monitor.run(), timeout=2.0)
    assert len(calls) == 1
    assert calls[0][1] == "heartbeat_timeout"
    assert session.connection.enqueued  # type: ignore[attr-defined]
    assert session.connection.enqueued[0].message_type is MessageType.PING  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_responsive_agent_never_trips_a_timeout() -> None:
    """Continued activity (simulated PONGs) keeps the monitor from timing out."""
    session = _make_session()
    calls: list[tuple[Session, str]] = []

    async def on_timeout(session: Session, reason: str) -> None:
        calls.append((session, reason))

    monitor = HeartbeatMonitor(
        session,
        session.connection,
        interval_seconds=0.01,
        heartbeat_timeout_seconds=0.01,
        idle_timeout_seconds=10.0,
        on_timeout=on_timeout,
    )
    task = asyncio.create_task(monitor.run())

    async def keep_alive() -> None:
        for _ in range(10):
            session.last_seen = datetime.now(UTC)
            await asyncio.sleep(0.005)

    await keep_alive()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == []
