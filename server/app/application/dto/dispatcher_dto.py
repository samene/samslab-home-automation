"""Command Dispatcher data transfer objects: the only shapes its admin endpoints ever see.

Built exclusively by ``app.dispatcher.dispatcher.CommandDispatcher``'s own
``status``/``queue_snapshot``/``running_snapshot``/``statistics`` accessors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domains.commands.models import CommandPriority


class DispatcherStatusDTO(BaseModel):
    """A snapshot of the dispatcher's own run state."""

    running: bool
    started_at: datetime | None
    queue_depth: int
    pending_ack_count: int
    running_count: int
    poll_interval_seconds: float


class DispatcherQueueItemDTO(BaseModel):
    """One command currently waiting in the in-memory dispatch queue."""

    command_id: UUID
    device_id: UUID
    priority: CommandPriority
    command_type: str
    enqueued_at: datetime


class DispatcherRunningItemDTO(BaseModel):
    """One command currently being tracked past dispatch (awaiting ack or a result)."""

    command_id: UUID
    device_id: UUID
    command_type: str
    phase: Literal["awaiting_ack", "running"]


class DispatcherStatisticsDTO(BaseModel):
    """A read-only view of the dispatcher's own operational counters."""

    commands_dispatched_total: int
    dispatch_failures_total: int
    dispatcher_retries_total: int
    dispatcher_timeouts_total: int
    queue_depth: int
    pending_ack_count: int
    running_count: int
