"""Typed API contracts and validation rules for the Command domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.commands.events import CommandEventType
from app.domains.commands.models import CommandPriority, CommandStatus
from app.domains.commands.validators import validate_command_type, validate_expiration_window


class CommandCreate(BaseModel):
    """Input for issuing a new command; every field is captured once and never edited."""

    device_id: UUID
    command_type: str = Field(min_length=3, max_length=150)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: CommandPriority = CommandPriority.NORMAL
    requested_by: str | None = Field(default=None, max_length=200)
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    correlation_id: UUID | None = None
    trace_id: str | None = Field(default=None, max_length=200)
    max_retries: int = Field(default=0, ge=0, le=10)

    @field_validator("command_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        """Keep command types generic, plugin-friendly identifiers, never an enum."""
        return validate_command_type(value)

    @model_validator(mode="after")
    def validate_window(self) -> CommandCreate:
        """Ensure an expiring command has a window in which it could still run."""
        validate_expiration_window(self.scheduled_at, self.expires_at)
        return self


class CancelRequest(BaseModel):
    """Optional operator context recorded on the resulting cancellation event."""

    reason: str | None = Field(default=None, max_length=500)


class CommandResultResponse(BaseModel):
    """Public representation of a command's single, terminal outcome."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    success: bool
    exit_code: int | None
    result: dict[str, Any]
    error_message: str | None
    duration_ms: int | None
    completed_at: datetime


class CommandEventResponse(BaseModel):
    """Public representation of one immutable lifecycle audit entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: CommandEventType
    timestamp: datetime
    details: dict[str, Any]


class CommandResponse(BaseModel):
    """Lightweight command representation used for list and search results."""

    model_config = ConfigDict(from_attributes=True)

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


class CommandDetailResponse(CommandResponse):
    """Full command representation including its result and lifecycle event trail."""

    result: CommandResultResponse | None
    events: list[CommandEventResponse]


class CommandPage(BaseModel):
    """Bounded pagination response for command search and listing."""

    items: list[CommandResponse]
    total: int
    offset: int
    limit: int
