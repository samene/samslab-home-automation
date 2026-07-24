"""SQLAlchemy repository implementing all Command domain persistence operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Case, ColumnElement, Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commands.events import CommandEventType
from app.domains.commands.models import (
    PRIORITY_RANK,
    TERMINAL_STATUSES,
    Command,
    CommandEvent,
    CommandPriority,
    CommandResult,
    CommandStatus,
)

_SORTABLE_COLUMNS: dict[str, Any] = {
    "created_at": Command.created_at,
    "scheduled_at": Command.scheduled_at,
    "expires_at": Command.expires_at,
    "status": Command.status,
}


def _priority_rank() -> Case[int]:
    """Rank priority by intended dispatch order, never by alphabetical string sort."""
    return case(
        *[(Command.priority == priority, rank) for priority, rank in PRIORITY_RANK.items()],
        else_=0,
    )


class CommandRepository:
    """Persist and query commands without leaking SQLAlchemy into application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    async def create(self, command: Command) -> Command:
        """Stage a new, immutable command for commit by the application service."""
        self._session.add(command)
        await self._session.flush()
        await self._session.refresh(command, attribute_names=["events", "result"])
        return command

    async def find(self, command_id: UUID) -> Command | None:
        """Find one command by UUID, or ``None`` if it does not exist or was deleted."""
        result = await self._session.execute(
            select(Command).where(Command.id == command_id, Command.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def find_pending(
        self, *, device_id: UUID | None = None, limit: int = 50
    ) -> list[Command]:
        """Return commands awaiting dispatch, highest priority and oldest first."""
        filters: list[ColumnElement[bool]] = [
            Command.status.in_((CommandStatus.PENDING, CommandStatus.QUEUED))
        ]
        if device_id is not None:
            filters.append(Command.device_id == device_id)
        result = await self._session.execute(
            select(Command)
            .where(*filters)
            .order_by(_priority_rank().desc(), Command.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().unique())

    async def find_by_device(
        self, device_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Command], int]:
        """List commands for one device, newest first, with total count."""
        filters: list[ColumnElement[bool]] = [Command.device_id == device_id]
        count = await self._session.scalar(select(func.count(Command.id)).where(*filters))
        result = await self._session.execute(
            select(Command)
            .where(*filters)
            .order_by(Command.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().unique()), count or 0

    async def find_all(
        self,
        *,
        status: CommandStatus | None,
        device_id: UUID | None,
        priority: CommandPriority | None,
        command_type: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        offset: int,
        limit: int,
        sort: str = "-created_at",
    ) -> tuple[list[Command], int]:
        """List commands with bounded filtering, pagination, and sorting."""
        filters: list[ColumnElement[bool]] = [Command.deleted_at.is_(None)]
        if status is not None:
            filters.append(Command.status == status)
        if device_id is not None:
            filters.append(Command.device_id == device_id)
        if priority is not None:
            filters.append(Command.priority == priority)
        if command_type is not None:
            filters.append(Command.command_type == command_type)
        if created_after is not None:
            filters.append(Command.created_at >= created_after)
        if created_before is not None:
            filters.append(Command.created_at <= created_before)
        count = await self._session.scalar(select(func.count(Command.id)).where(*filters))
        result = await self._session.execute(
            self._apply_sort(select(Command).where(*filters), sort).offset(offset).limit(limit)
        )
        return list(result.scalars().unique()), count or 0

    async def find_interrupted(self) -> list[Command]:
        """Return every command left DISPATCHED or RUNNING by a previous process's crash/restart."""
        result = await self._session.execute(
            select(Command).where(
                Command.status.in_((CommandStatus.DISPATCHED, CommandStatus.RUNNING)),
                Command.deleted_at.is_(None),
            )
        )
        return list(result.scalars().unique())

    async def find_expirable(self, as_of: datetime) -> list[Command]:
        """Return every non-terminal command whose expiration window has passed."""
        result = await self._session.execute(
            select(Command).where(
                Command.expires_at.is_not(None),
                Command.expires_at <= as_of,
                Command.status.not_in(TERMINAL_STATUSES),
            )
        )
        return list(result.scalars().unique())

    async def update_status(
        self,
        command: Command,
        *,
        status: CommandStatus,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> Command:
        """Apply the only fields a lifecycle transition is ever allowed to change."""
        command.status = status
        if started_at is not None:
            command.started_at = started_at
        if completed_at is not None:
            command.completed_at = completed_at
        await self._session.flush()
        return command

    async def store_result(
        self,
        command: Command,
        *,
        success: bool,
        exit_code: int | None,
        result: dict[str, Any],
        error_message: str | None,
        duration_ms: int | None,
    ) -> CommandResult:
        """Persist a command's single terminal outcome, separate from its payload."""
        command_result = CommandResult(
            success=success,
            exit_code=exit_code,
            result=result,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        command.result = command_result
        await self._session.flush()
        return command_result

    async def append_event(
        self,
        command: Command,
        *,
        event_type: CommandEventType,
        details: dict[str, Any] | None = None,
    ) -> CommandEvent:
        """Append one immutable audit event for a lifecycle transition."""
        event = CommandEvent(event_type=event_type, details=details or {})
        command.events.append(event)
        await self._session.flush()
        return event

    async def cancel(self, command: Command, *, cancelled_at: datetime) -> Command:
        """Transition a command to CANCELLED and record when that happened."""
        command.status = CommandStatus.CANCELLED
        command.completed_at = cancelled_at
        await self._session.flush()
        return command

    async def expire(
        self, command: Command, *, status: CommandStatus, expired_at: datetime
    ) -> Command:
        """Transition a command to EXPIRED or TIMEOUT once its window has passed."""
        command.status = status
        command.completed_at = expired_at
        await self._session.flush()
        return command

    async def increment_retry(self, command: Command) -> Command:
        """Record one more delivery-retry attempt against a command; status is untouched."""
        command.retry_count += 1
        await self._session.flush()
        return command

    async def soft_delete(self, command: Command, *, at: datetime) -> Command:
        """Stamp deleted_at; status/payload are never touched, only visibility changes."""
        command.deleted_at = at
        await self._session.flush()
        return command

    def _apply_sort(self, statement: Select[tuple[Command]], sort: str) -> Select[tuple[Command]]:
        """Resolve a validated ``[-]field`` sort token to a concrete ORDER BY clause.

        Always appends ``Command.id`` as a secondary key so ties on the
        primary sort column (routine for ``created_at``: SQLite's
        ``CURRENT_TIMESTAMP`` default only has whole-second resolution, so
        two commands created in the same second tie exactly) get a stable,
        reproducible order — without this, which of two tied rows comes
        first can depend on the query plan SQLite happens to pick (e.g. a
        direct index scan vs. a temp B-tree sort), which in turn means a
        `LIMIT`/`OFFSET` page boundary could return a row twice or skip one
        entirely across two otherwise-identical requests.
        """
        descending = sort.startswith("-")
        key = sort[1:] if descending else sort
        column = _priority_rank() if key == "priority" else _SORTABLE_COLUMNS.get(key)
        if column is None:
            column = Command.created_at
            descending = True
        primary = column.desc() if descending else column.asc()
        tiebreaker = Command.id.desc() if descending else Command.id.asc()
        return statement.order_by(primary, tiebreaker)
