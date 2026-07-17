"""SQLAlchemy persistence models owned exclusively by the Command domain."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domains.commands.events import CommandEventType


class CommandStatus(StrEnum):
    """Lifecycle state of a command, enforced by the domain's explicit state machine."""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    TIMEOUT = "TIMEOUT"


class CommandPriority(StrEnum):
    """Dispatch priority; ordering semantics live in ``PRIORITY_RANK``, not string sort."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


PRIORITY_RANK: Final[dict[CommandPriority, int]] = {
    CommandPriority.LOW: 0,
    CommandPriority.NORMAL: 1,
    CommandPriority.HIGH: 2,
    CommandPriority.CRITICAL: 3,
}

TERMINAL_STATUSES: Final[frozenset[CommandStatus]] = frozenset(
    {
        CommandStatus.COMPLETED,
        CommandStatus.FAILED,
        CommandStatus.CANCELLED,
        CommandStatus.EXPIRED,
        CommandStatus.TIMEOUT,
    }
)

json_type = JSON().with_variant(JSONB, "postgresql")


class Command(Base):
    """An immutable statement of intent targeting one device; only status/timing evolve."""

    __tablename__ = "commands"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    command_type: Mapped[str] = mapped_column(String(150), index=True)
    status: Mapped[CommandStatus] = mapped_column(
        Enum(CommandStatus, native_enum=False, length=20),
        default=CommandStatus.PENDING,
        index=True,
    )
    priority: Mapped[CommandPriority] = mapped_column(
        Enum(CommandPriority, native_enum=False, length=20),
        default=CommandPriority.NORMAL,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)
    requested_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    correlation_id: Mapped[UUID] = mapped_column(default=uuid4, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    # Soft-delete only, matching the Device Registry pattern — a deleted
    # command still exists for whatever audit/debugging need surfaces later,
    # it's just excluded from every normal query (find/find_all). Only a
    # terminal command may be deleted (see CommandService.delete_command);
    # this never mutates status/payload, so "commands are immutable, only
    # status evolves" still holds.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    result: Mapped[CommandResult | None] = relationship(
        back_populates="command",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    events: Mapped[list[CommandEvent]] = relationship(
        back_populates="command",
        cascade="all, delete-orphan",
        order_by="CommandEvent.timestamp",
        lazy="selectin",
    )


class CommandResult(Base):
    """The single terminal outcome of a command, persisted independently of its payload."""

    __tablename__ = "command_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("commands.id", ondelete="CASCADE"), unique=True, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    command: Mapped[Command] = relationship(back_populates="result")


class CommandEvent(Base):
    """One immutable, append-only audit record of a command lifecycle transition."""

    __tablename__ = "command_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("commands.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[CommandEventType] = mapped_column(
        Enum(CommandEventType, native_enum=False, length=30), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)

    command: Mapped[Command] = relationship(back_populates="events")
