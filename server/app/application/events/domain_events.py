"""Domain events published on the application event bus.

These are distinct from a domain's own persisted audit trail (e.g.
``CommandEvent`` rows) — they are transient, in-process notifications that
let the application layer react to a cross-cutting lifecycle moment without
any domain or repository needing to know the event bus exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DeviceRegistered:
    """Published after a device is successfully registered."""

    device_id: UUID
    device_name: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DeviceHeartbeat:
    """Published after a device heartbeat is recorded."""

    device_id: UUID
    status: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandCreated:
    """Published after a new command is created."""

    command_id: UUID
    device_id: UUID
    command_type: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandDispatched:
    """Published after a command is handed to a transport for delivery."""

    command_id: UUID
    device_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandCompleted:
    """Published after a command reaches a successful terminal state."""

    command_id: UUID
    device_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandFailed:
    """Published after a command reaches a failed terminal state."""

    command_id: UUID
    device_id: UUID
    error_message: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandTimedOut:
    """Published after a dispatched or running command never produced a result in time."""

    command_id: UUID
    device_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandAckReceived:
    """Published by the WebSocket Gateway when a device acknowledges a command.

    A transient, in-process signal only — the Command Dispatcher subscribes to
    this to know when to transition a command to RUNNING; the gateway itself
    has no notion of what a command dispatcher does with it.
    """

    command_id: UUID
    device_id: UUID
    message_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CommandResultReceived:
    """Published by the WebSocket Gateway when a device reports a command's outcome."""

    command_id: UUID
    device_id: UUID
    success: bool
    result: dict[str, Any]
    error_message: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class UserLoggedIn:
    """Published after a user successfully authenticates."""

    user_id: UUID
    username: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class TerminalOpenedReceived:
    """Published by the WebSocket Gateway when an agent confirms a PTY session is open.

    A transient, in-process signal only — ``TerminalSessionManager``
    (``server/app/terminal/``) subscribes to this to notify every browser
    connection attached to the session; the gateway itself has no notion of
    what a terminal session is beyond one more envelope type to relay.
    """

    device_id: UUID
    session_id: UUID
    shell: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class TerminalOutputReceived:
    """Published by the WebSocket Gateway when an agent forwards PTY output bytes."""

    device_id: UUID
    session_id: UUID
    data: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class TerminalClosedReceived:
    """Published by the WebSocket Gateway when an agent reports a PTY session ended."""

    device_id: UUID
    session_id: UUID
    reason: str
    exit_code: int | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class TerminalErrorReceived:
    """Published by the WebSocket Gateway when an agent reports a terminal-scoped error."""

    device_id: UUID
    session_id: UUID | None
    code: str
    message: str
    occurred_at: datetime
