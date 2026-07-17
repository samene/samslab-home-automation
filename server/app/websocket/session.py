"""In-memory session state for one authenticated device connection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domains.auth.schemas import Principal
from app.websocket.connection import Connection, PendingAck


class ConnectionState(StrEnum):
    """The lifecycle state of one WebSocket connection."""

    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


@dataclass
class Session:
    """Everything the gateway tracks about one connected device, kept only in memory.

    Never persisted: a server restart drops every session, and the Device
    Registry's own ``last_seen``/``status`` fields (updated through the
    Application Layer) remain the durable record of device liveness.
    """

    device_id: UUID
    connection_id: UUID
    connected_at: datetime
    last_seen: datetime
    protocol_version: int
    authenticated_principal: Principal
    connection: Connection
    agent_version: str | None = None
    remote_ip: str | None = None
    connection_state: ConnectionState = ConnectionState.CONNECTING

    @property
    def pending_messages(self) -> dict[UUID, PendingAck]:
        """Expose the connection's in-flight, unacknowledged outgoing messages."""
        return self.connection.pending_acks
