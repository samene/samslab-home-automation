"""Envelope and payload schemas — re-exported from ``shared.protocol``, plus gateway-only DTOs.

The wire-format models live in ``shared/protocol/schemas.py`` so the cloud
server and the Raspberry Pi agent share exactly one source of truth.
``SessionSummaryDTO`` stays here: it is a read-only shape for this gateway's
own admin endpoints, not part of the wire protocol itself.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from shared.protocol.schemas import (
    CommandAckPayload,
    CommandPayload,
    CommandResultPayload,
    Envelope,
    ErrorPayload,
    EventPayload,
    GoodbyePayload,
    HelloPayload,
    LogPayload,
    MessageAckPayload,
    PingPayload,
    PongPayload,
    WelcomePayload,
)


class SessionSummaryDTO(BaseModel):
    """The read-only session shape exposed by the admin ``/ws/sessions`` endpoints."""

    device_id: UUID
    connection_id: UUID
    connected_at: datetime
    last_seen: datetime
    protocol_version: int
    agent_version: str | None
    remote_ip: str | None
    connection_state: str
    pending_message_count: int


__all__ = [
    "CommandAckPayload",
    "CommandPayload",
    "CommandResultPayload",
    "Envelope",
    "ErrorPayload",
    "EventPayload",
    "GoodbyePayload",
    "HelloPayload",
    "LogPayload",
    "MessageAckPayload",
    "PingPayload",
    "PongPayload",
    "SessionSummaryDTO",
    "WelcomePayload",
]
