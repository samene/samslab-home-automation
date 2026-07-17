"""Transactional Command domain application service and its explicit state machine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from app.domains.commands.events import CommandEventType
from app.domains.commands.exceptions import CommandNotFound, InvalidStateTransition
from app.domains.commands.models import (
    TERMINAL_STATUSES,
    Command,
    CommandPriority,
    CommandStatus,
)
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate

# The explicit command state machine: source status -> the target statuses it may
# transition to. Every status absent as a key (the terminal ones) allows nothing
# further — "completed commands cannot restart."
ALLOWED_TRANSITIONS: Final[dict[CommandStatus, frozenset[CommandStatus]]] = {
    CommandStatus.PENDING: frozenset(
        {
            CommandStatus.QUEUED,
            CommandStatus.DISPATCHED,
            CommandStatus.CANCELLED,
            CommandStatus.EXPIRED,
        }
    ),
    CommandStatus.QUEUED: frozenset(
        {CommandStatus.DISPATCHED, CommandStatus.CANCELLED, CommandStatus.EXPIRED}
    ),
    CommandStatus.DISPATCHED: frozenset(
        {
            CommandStatus.RUNNING,
            CommandStatus.FAILED,
            CommandStatus.CANCELLED,
            CommandStatus.EXPIRED,
            CommandStatus.TIMEOUT,
        }
    ),
    CommandStatus.RUNNING: frozenset(
        {
            CommandStatus.COMPLETED,
            CommandStatus.FAILED,
            CommandStatus.CANCELLED,
            CommandStatus.TIMEOUT,
        }
    ),
}


def ensure_transition_allowed(current: CommandStatus, target: CommandStatus) -> None:
    """Raise unless the state machine permits ``current -> target``."""
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidStateTransition(f"Cannot transition command from {current} to {target}")


class CommandService:
    """Coordinate Command domain use cases and enforce the lifecycle state machine."""

    def __init__(self, repository: CommandRepository) -> None:
        """Inject the command repository; this domain never depends on another."""
        self._repository = repository

    async def create_command(self, request: CommandCreate) -> Command:
        """Create a new, immutable command targeting the given device.

        Confirming the device exists and is enabled is a cross-domain concern and
        is the caller's (application layer's) responsibility, not this domain's.
        """
        command = Command(
            device_id=request.device_id,
            command_type=request.command_type,
            payload=request.payload,
            priority=request.priority,
            requested_by=request.requested_by,
            scheduled_at=request.scheduled_at,
            expires_at=request.expires_at,
            correlation_id=request.correlation_id or uuid4(),
            trace_id=request.trace_id,
            max_retries=request.max_retries,
            status=CommandStatus.PENDING,
        )
        command = await self._repository.create(command)
        await self._repository.append_event(
            command,
            event_type=CommandEventType.COMMAND_CREATED,
            details={"command_type": command.command_type, "priority": command.priority.value},
        )
        return command

    async def get_command(self, command_id: UUID) -> Command:
        """Return one command or raise the domain's not-found error."""
        command = await self._repository.find(command_id)
        if command is None:
            raise CommandNotFound(f"Command '{command_id}' was not found")
        return command

    async def list_commands(
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
        sort: str,
    ) -> tuple[list[Command], int]:
        """List commands using repository-owned filtering, pagination, and sorting."""
        return await self._repository.find_all(
            status=status,
            device_id=device_id,
            priority=priority,
            command_type=command_type,
            created_after=created_after,
            created_before=created_before,
            offset=offset,
            limit=limit,
            sort=sort,
        )

    async def find_pending(
        self, *, device_id: UUID | None = None, limit: int = 50
    ) -> list[Command]:
        """Return commands awaiting dispatch, highest priority and oldest first.

        A thin pass-through to the repository's own ordering — the Command
        domain never re-derives dispatch order, it only ever exposes the
        one query the repository already implements for it.
        """
        return await self._repository.find_pending(device_id=device_id, limit=limit)

    async def delete_command(self, command_id: UUID) -> None:
        """Soft-delete a command once it's reached a terminal state.

        Restricted to terminal commands so a still-in-flight command (one
        the dispatcher or an agent may still be actively tracking) can never
        disappear from underneath them — deleting is a history-cleanup
        action, not a way to cancel something in progress (use
        ``cancel_command`` for that, before deleting the now-terminal result).
        """
        command = await self.get_command(command_id)
        if command.status not in TERMINAL_STATUSES:
            raise InvalidStateTransition(
                f"Command '{command_id}' is {command.status}, not yet terminal — cancel it first"
            )
        await self._repository.soft_delete(command, at=datetime.now(UTC))

    async def cancel_command(self, command_id: UUID, *, reason: str | None = None) -> Command:
        """Cancel a command that has not yet reached a terminal state."""
        command = await self.get_command(command_id)
        ensure_transition_allowed(command.status, CommandStatus.CANCELLED)
        command = await self._repository.cancel(command, cancelled_at=datetime.now(UTC))
        await self._repository.append_event(
            command,
            event_type=CommandEventType.COMMAND_CANCELLED,
            details={"reason": reason} if reason else {},
        )
        return command

    async def mark_dispatched(self, command_id: UUID) -> Command:
        """Record that a command has been handed to a transport for delivery."""
        command = await self.get_command(command_id)
        ensure_transition_allowed(command.status, CommandStatus.DISPATCHED)
        command = await self._repository.update_status(command, status=CommandStatus.DISPATCHED)
        await self._repository.append_event(command, event_type=CommandEventType.COMMAND_DISPATCHED)
        return command

    async def mark_running(self, command_id: UUID) -> Command:
        """Record that execution has started on the target device."""
        command = await self.get_command(command_id)
        ensure_transition_allowed(command.status, CommandStatus.RUNNING)
        command = await self._repository.update_status(
            command, status=CommandStatus.RUNNING, started_at=datetime.now(UTC)
        )
        await self._repository.append_event(command, event_type=CommandEventType.COMMAND_STARTED)
        return command

    async def complete_command(
        self,
        command_id: UUID,
        *,
        result: dict[str, Any],
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> Command:
        """Record a successful terminal outcome; the command can never restart."""
        command = await self.get_command(command_id)
        ensure_transition_allowed(command.status, CommandStatus.COMPLETED)
        command = await self._repository.update_status(
            command, status=CommandStatus.COMPLETED, completed_at=datetime.now(UTC)
        )
        await self._repository.store_result(
            command,
            success=True,
            exit_code=exit_code,
            result=result,
            error_message=None,
            duration_ms=duration_ms,
        )
        await self._repository.append_event(command, event_type=CommandEventType.COMMAND_COMPLETED)
        return command

    async def fail_command(
        self,
        command_id: UUID,
        *,
        error_message: str,
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> Command:
        """Record a failed terminal outcome; the command can never restart."""
        command = await self.get_command(command_id)
        ensure_transition_allowed(command.status, CommandStatus.FAILED)
        command = await self._repository.update_status(
            command, status=CommandStatus.FAILED, completed_at=datetime.now(UTC)
        )
        await self._repository.store_result(
            command,
            success=False,
            exit_code=exit_code,
            result={},
            error_message=error_message,
            duration_ms=duration_ms,
        )
        await self._repository.append_event(
            command,
            event_type=CommandEventType.COMMAND_FAILED,
            details={"error_message": error_message},
        )
        return command

    async def mark_timeout(self, command_id: UUID) -> Command:
        """Record that a dispatched or running command never produced a result in time."""
        command = await self.get_command(command_id)
        ensure_transition_allowed(command.status, CommandStatus.TIMEOUT)
        command = await self._repository.expire(
            command, status=CommandStatus.TIMEOUT, expired_at=datetime.now(UTC)
        )
        await self._repository.append_event(command, event_type=CommandEventType.COMMAND_TIMEOUT)
        return command

    async def record_retry(self, command_id: UUID) -> Command:
        """Record one more delivery-retry attempt; this never changes ``status``."""
        command = await self.get_command(command_id)
        command = await self._repository.increment_retry(command)
        await self._repository.append_event(
            command,
            event_type=CommandEventType.COMMAND_RETRY_SCHEDULED,
            details={"retry_count": command.retry_count},
        )
        return command

    async def expire_old_commands(self, *, now: datetime | None = None) -> int:
        """Sweep past-expiration commands to EXPIRED (or TIMEOUT if already running)."""
        as_of = now or datetime.now(UTC)
        expirable = await self._repository.find_expirable(as_of)
        for command in expirable:
            target = (
                CommandStatus.TIMEOUT
                if command.status is CommandStatus.RUNNING
                else CommandStatus.EXPIRED
            )
            ensure_transition_allowed(command.status, target)
            await self._repository.expire(command, status=target, expired_at=as_of)
            event_type = (
                CommandEventType.COMMAND_TIMEOUT
                if target is CommandStatus.TIMEOUT
                else CommandEventType.COMMAND_EXPIRED
            )
            await self._repository.append_event(command, event_type=event_type)
        return len(expirable)
