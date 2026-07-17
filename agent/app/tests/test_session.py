"""Tests for the agent's in-memory session state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.session import SessionState


def test_session_starts_disconnected() -> None:
    """A fresh session reports not connected and not authenticated."""
    session = SessionState()
    assert session.connected is False
    assert session.authenticated is False
    assert session.connection_id is None


def test_mark_connected_sets_connected_only() -> None:
    """mark_connected reflects an open transport before authentication completes."""
    session = SessionState()
    session.mark_connected()
    assert session.connected is True
    assert session.authenticated is False


def test_mark_authenticated_sets_full_session() -> None:
    """mark_authenticated records every handshake fact."""
    session = SessionState()
    connection_id = uuid4()
    connected_at = datetime.now(UTC)

    session.mark_authenticated(
        connection_id=connection_id,
        protocol_version=1,
        connected_at=connected_at,
        agent_version="0.1.0",
        server_version=None,
    )

    assert session.connected is True
    assert session.authenticated is True
    assert session.connection_id == connection_id
    assert session.protocol_version == 1
    assert session.agent_version == "0.1.0"
    assert session.connected_at == connected_at


def test_record_heartbeat_updates_last_heartbeat_at() -> None:
    """record_heartbeat stores the given timestamp."""
    session = SessionState()
    at = datetime.now(UTC)
    session.record_heartbeat(at)
    assert session.last_heartbeat_at == at


def test_record_heartbeat_ack_updates_last_heartbeat_ack_at() -> None:
    """record_heartbeat_ack stores the given timestamp."""
    session = SessionState()
    at = datetime.now(UTC)
    session.record_heartbeat_ack(at)
    assert session.last_heartbeat_ack_at == at


def test_mark_disconnected_resets_connection_scoped_state() -> None:
    """mark_disconnected clears everything scoped to the closed connection."""
    session = SessionState()
    session.mark_authenticated(
        connection_id=uuid4(), protocol_version=1, connected_at=datetime.now(UTC)
    )
    session.record_heartbeat(datetime.now(UTC))

    session.mark_disconnected()

    assert session.connected is False
    assert session.authenticated is False
    assert session.connection_id is None
    assert session.connected_at is None
    assert session.last_heartbeat_at is None


def test_connection_duration_seconds_none_when_not_connected() -> None:
    """Duration is undefined before any connection was authenticated."""
    session = SessionState()
    assert session.connection_duration_seconds(now=datetime.now(UTC)) is None


def test_connection_duration_seconds_computes_elapsed_time() -> None:
    """Duration reflects elapsed time since ``connected_at``."""
    session = SessionState()
    connected_at = datetime(2026, 1, 1, tzinfo=UTC)
    session.mark_authenticated(connection_id=uuid4(), protocol_version=1, connected_at=connected_at)

    now = datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)

    assert session.connection_duration_seconds(now=now) == 30.0
