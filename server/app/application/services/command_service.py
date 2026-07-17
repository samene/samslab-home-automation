"""Application service orchestrating Command use cases across the Command and Device domains.

This is the layer where the cross-domain rule "a command's target device must
exist and be enabled" lives — neither domain service is allowed to know about
the other, so only this application service may call both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.dto.command_dto import CommandDetailDTO, CommandPageDTO
from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    CommandCompleted,
    CommandCreated,
    CommandDispatched,
    CommandFailed,
    CommandTimedOut,
)
from app.application.exceptions import DeviceDisabledError, translate_domain_error
from app.application.mappers.command_mapper import to_command_detail_dto, to_command_dto
from app.application.validators import PaginationParams, validate_sort_field
from app.domains.commands.exceptions import CommandDomainError
from app.domains.commands.models import CommandPriority, CommandStatus
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.exceptions import DeviceDomainError
from app.domains.devices.service import DeviceService

_LIST_SORT_FIELDS = frozenset({"created_at", "scheduled_at", "expires_at", "priority", "status"})


class CommandApplicationService:
    """Expose Command lifecycle use cases as DTOs, owning the only cross-domain checks."""

    def __init__(
        self,
        command_service: CommandService,
        device_service: DeviceService,
        event_bus: EventBus,
    ) -> None:
        """Wrap both domain services; publish lifecycle events on the shared event bus."""
        self._commands = command_service
        self._devices = device_service
        self._event_bus = event_bus

    async def create_command(self, request: CommandCreate) -> CommandDetailDTO:
        """Create a command after confirming its target device exists and is enabled."""
        try:
            device = await self._devices.get_device(request.device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        if not device.enabled:
            raise DeviceDisabledError(f"Device '{request.device_id}' is disabled")

        try:
            command = await self._commands.create_command(request)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        await self._event_bus.publish(
            CommandCreated(
                command_id=command.id,
                device_id=command.device_id,
                command_type=command.command_type,
                occurred_at=command.created_at,
            )
        )
        return to_command_detail_dto(command)

    async def get_command(self, command_id: UUID) -> CommandDetailDTO:
        """Return one command with its result and event trail."""
        try:
            command = await self._commands.get_command(command_id)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        return to_command_detail_dto(command)

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
    ) -> CommandPageDTO:
        """List commands with bounded, centrally validated pagination and sorting."""
        pagination = PaginationParams.create(offset=offset, limit=limit)
        validated_sort = validate_sort_field(sort, _LIST_SORT_FIELDS)
        commands, total = await self._commands.list_commands(
            status=status,
            device_id=device_id,
            priority=priority,
            command_type=command_type,
            created_after=created_after,
            created_before=created_before,
            offset=pagination.offset,
            limit=pagination.limit,
            sort=validated_sort,
        )
        return CommandPageDTO(
            items=[to_command_dto(command) for command in commands],
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    async def list_pending_commands(
        self, *, device_id: UUID | None = None, limit: int = 50
    ) -> list[CommandDetailDTO]:
        """Return commands awaiting dispatch, highest priority and oldest first."""
        commands = await self._commands.find_pending(device_id=device_id, limit=limit)
        return [to_command_detail_dto(command) for command in commands]

    async def cancel_command(
        self, command_id: UUID, *, reason: str | None = None
    ) -> CommandDetailDTO:
        """Cancel a command that has not yet reached a terminal state."""
        try:
            command = await self._commands.cancel_command(command_id, reason=reason)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        return to_command_detail_dto(command)

    async def delete_command(self, command_id: UUID) -> None:
        """Soft-delete a terminal command from history."""
        try:
            await self._commands.delete_command(command_id)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error

    async def mark_dispatched(self, command_id: UUID) -> CommandDetailDTO:
        """Record that a command has been handed to a transport for delivery."""
        try:
            command = await self._commands.mark_dispatched(command_id)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        await self._event_bus.publish(
            CommandDispatched(
                command_id=command.id, device_id=command.device_id, occurred_at=datetime.now(UTC)
            )
        )
        return to_command_detail_dto(command)

    async def mark_running(self, command_id: UUID) -> CommandDetailDTO:
        """Record that execution has started on the target device."""
        try:
            command = await self._commands.mark_running(command_id)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        return to_command_detail_dto(command)

    async def complete_command(
        self,
        command_id: UUID,
        *,
        result: dict[str, Any],
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> CommandDetailDTO:
        """Record a successful terminal outcome and publish ``CommandCompleted``."""
        try:
            command = await self._commands.complete_command(
                command_id, result=result, exit_code=exit_code, duration_ms=duration_ms
            )
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        assert command.completed_at is not None  # a successful completion always sets this
        await self._event_bus.publish(
            CommandCompleted(
                command_id=command.id, device_id=command.device_id, occurred_at=command.completed_at
            )
        )
        return to_command_detail_dto(command)

    async def fail_command(
        self,
        command_id: UUID,
        *,
        error_message: str,
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> CommandDetailDTO:
        """Record a failed terminal outcome and publish ``CommandFailed``."""
        try:
            command = await self._commands.fail_command(
                command_id,
                error_message=error_message,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        assert command.completed_at is not None  # a failure always sets this
        await self._event_bus.publish(
            CommandFailed(
                command_id=command.id,
                device_id=command.device_id,
                error_message=error_message,
                occurred_at=command.completed_at,
            )
        )
        return to_command_detail_dto(command)

    async def mark_timeout(self, command_id: UUID) -> CommandDetailDTO:
        """Record that a dispatched/running command never produced a result in time."""
        try:
            command = await self._commands.mark_timeout(command_id)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        assert command.completed_at is not None  # a timeout always sets this
        await self._event_bus.publish(
            CommandTimedOut(
                command_id=command.id, device_id=command.device_id, occurred_at=command.completed_at
            )
        )
        return to_command_detail_dto(command)

    async def record_retry(self, command_id: UUID) -> CommandDetailDTO:
        """Record one more delivery-retry attempt; this never changes the command's status."""
        try:
            command = await self._commands.record_retry(command_id)
        except CommandDomainError as error:
            raise translate_domain_error(error) from error
        return to_command_detail_dto(command)

    async def expire_old_commands(self, *, now: datetime | None = None) -> int:
        """Sweep past-expiration commands to EXPIRED or TIMEOUT."""
        return await self._commands.expire_old_commands(now=now)
