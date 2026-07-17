"""Dispatcher-only operational events, published on the shared application event bus.

Distinct from ``app.application.events.domain_events`` — those describe a
command's own lifecycle (dispatched, completed, timed out, ...) and are
published by ``CommandApplicationService`` itself. These describe the
dispatcher's *own* internal operations (queueing, retrying, giving up) and
are published by the dispatcher package for observability/testing, never
consumed by another domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CommandQueued:
    """Published when a discovered command is added to the in-memory dispatch queue."""

    command_id: UUID
    device_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryFailed:
    """Published when a command could not be handed to the WebSocket Gateway at all."""

    command_id: UUID
    device_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DispatchRetryScheduled:
    """Published when an unacknowledged command is redelivered after a backoff wait."""

    command_id: UUID
    device_id: UUID
    retry_count: int
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DispatchExhausted:
    """Published when an unacknowledged command has used up its retry budget."""

    command_id: UUID
    device_id: UUID
    retry_count: int
    occurred_at: datetime
