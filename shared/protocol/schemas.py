"""Pydantic message envelope and payload schemas for the WebSocket protocol.

Every message on the wire is one ``Envelope``. Its ``message_type`` selects which
payload schema validates ``payload`` — there is no raw dict manipulation
anywhere a transport built on this protocol. An envelope with an unrecognized
``message_type`` or a payload that fails its schema is rejected before it
reaches any handler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.protocol.message_types import MessageType


class Envelope(BaseModel):
    """The one message shape exchanged over the WebSocket connection."""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    protocol_version: int
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: UUID | None = None
    trace_id: str | None = None


class HelloPayload(BaseModel):
    """Credentials and capabilities offered by a connecting agent.

    The negotiated protocol version comes from the envelope's own
    ``protocol_version`` field, not from this payload.
    """

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1)
    agent_version: str = Field(min_length=1, max_length=100)
    capabilities: list[str] = Field(default_factory=list)
    resume_cursor: str | None = None


class WelcomePayload(BaseModel):
    """The server's handshake acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    server_time: datetime
    protocol_version: int
    heartbeat_interval_seconds: float
    heartbeat_timeout_seconds: float


class PingPayload(BaseModel):
    """A liveness probe; either side may send one."""

    model_config = ConfigDict(extra="forbid")

    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PongPayload(BaseModel):
    """The reply to a ``PingPayload``, echoing back what was pinged."""

    model_config = ConfigDict(extra="forbid")

    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CommandPayload(BaseModel):
    """A command dispatch envelope; execution is out of scope for this schema."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    command_type: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CommandAckPayload(BaseModel):
    """An agent's acknowledgement that it accepted a command."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID


class CommandResultPayload(BaseModel):
    """A command's terminal outcome as reported by the agent."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    success: bool
    result: dict[str, Any] | None = None
    error_message: str | None = None


class EventPayload(BaseModel):
    """An arbitrary agent-originated event."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class LogPayload(BaseModel):
    """A structured log line forwarded from an agent."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(min_length=1, max_length=20)
    message: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    """An application-level protocol error reported by either side."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class MessageAckPayload(BaseModel):
    """Acknowledges receipt of exactly one prior message by ID."""

    model_config = ConfigDict(extra="forbid")

    acknowledged_message_id: UUID


class GoodbyePayload(BaseModel):
    """A graceful, client- or server-initiated disconnect notice."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
