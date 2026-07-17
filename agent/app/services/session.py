"""The agent's local view of its own connection — never persisted, in-memory only.

Mirrors the cloud server's own ``SessionManager`` convention (never persisted,
one instance per running process) but from the other end of the same
connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class SessionState:
    """Point-in-time facts about the agent's current (or most recent) connection."""

    connected: bool = False
    authenticated: bool = False
    connection_id: UUID | None = None
    protocol_version: int | None = None
    agent_version: str | None = None
    server_version: str | None = None
    connected_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_heartbeat_ack_at: datetime | None = None

    def mark_connected(self) -> None:
        """Record that the transport is open, ahead of authentication completing."""
        self.connected = True

    def mark_authenticated(
        self,
        *,
        connection_id: UUID,
        protocol_version: int,
        connected_at: datetime,
        agent_version: str | None = None,
        server_version: str | None = None,
    ) -> None:
        """Record a completed HELLO/WELCOME handshake."""
        self.connected = True
        self.authenticated = True
        self.connection_id = connection_id
        self.protocol_version = protocol_version
        self.agent_version = agent_version
        self.server_version = server_version
        self.connected_at = connected_at

    def record_heartbeat(self, at: datetime) -> None:
        """Record that the agent sent a heartbeat PING at ``at``."""
        self.last_heartbeat_at = at

    def record_heartbeat_ack(self, at: datetime) -> None:
        """Record that the server replied PONG to the agent's heartbeat at ``at``."""
        self.last_heartbeat_ack_at = at

    def mark_disconnected(self) -> None:
        """Reset connection-scoped state after the transport closes."""
        self.connected = False
        self.authenticated = False
        self.connection_id = None
        self.connected_at = None
        self.last_heartbeat_at = None
        self.last_heartbeat_ack_at = None

    def connection_duration_seconds(self, *, now: datetime) -> float | None:
        """Seconds since the current connection was authenticated, or ``None`` if not connected."""
        if self.connected_at is None:
            return None
        return (now - self.connected_at).total_seconds()
