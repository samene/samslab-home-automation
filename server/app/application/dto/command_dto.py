"""Command data transfer objects: the only command shape REST controllers ever see.

Independent of both the SQLAlchemy ``Command``/``CommandResult``/``CommandEvent``
models and of the commands domain's own ``schemas.py`` response models. Built
exclusively by ``app.application.mappers.command_mapper``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.domains.commands.events import CommandEventType
from app.domains.commands.models import CommandPriority, CommandStatus


class CommandResultDTO(BaseModel):
    """A command's single, terminal outcome."""

    id: UUID
    success: bool
    exit_code: int | None
    result: dict[str, Any]
    error_message: str | None
    duration_ms: int | None
    completed_at: datetime


class CommandEventDTO(BaseModel):
    """One immutable lifecycle audit entry."""

    id: UUID
    event_type: CommandEventType
    timestamp: datetime
    details: dict[str, Any]


class CommandDTO(BaseModel):
    """A lightweight command representation used for list/search results."""

    id: UUID
    device_id: UUID
    command_type: str
    status: CommandStatus
    priority: CommandPriority
    payload: dict[str, Any]
    requested_by: str | None
    created_at: datetime
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    correlation_id: UUID
    trace_id: str | None
    retry_count: int
    max_retries: int


class CommandDetailDTO(CommandDTO):
    """The full command representation including its result and event trail."""

    result: CommandResultDTO | None
    events: list[CommandEventDTO]


class CommandPageDTO(BaseModel):
    """A bounded, paginated page of commands."""

    items: list[CommandDTO]
    total: int
    offset: int
    limit: int
