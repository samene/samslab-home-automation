"""FastAPI delivery adapter for Command domain administration endpoints.

Contains no business logic: each route only resolves the application
service, forwards validated input to it, and returns the DTO it produces.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.application.dto.command_dto import CommandDetailDTO, CommandPageDTO
from app.application.events.bus import EventBus
from app.application.services.command_service import CommandApplicationService
from app.core.database import Database
from app.dependencies import get_database, get_event_bus
from app.domains.commands.models import CommandPriority, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CancelRequest, CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.service import DeviceService

router = APIRouter(prefix="/commands", tags=["Commands"])


async def get_command_application_service(
    database: Database = Depends(get_database),
    event_bus: EventBus = Depends(get_event_bus),
) -> AsyncIterator[CommandApplicationService]:
    """Inject a transaction-scoped application service and commit on success only."""
    async with database.session_factory() as session:
        try:
            yield CommandApplicationService(
                CommandService(CommandRepository(session)),
                DeviceService(DeviceRepository(session)),
                event_bus,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.get("", response_model=CommandPageDTO)
async def list_commands(
    service: CommandApplicationService = Depends(get_command_application_service),
    status_filter: CommandStatus | None = Query(default=None, alias="status"),
    device_id: UUID | None = Query(default=None, alias="device"),
    priority: CommandPriority | None = Query(default=None),
    command_type: str | None = Query(default=None, min_length=1, max_length=150),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    offset: int = Query(default=0),
    limit: int = Query(default=50),
    sort: str = Query(default="-created_at"),
) -> CommandPageDTO:
    """List commands with status/device/priority/type/time-range filters."""
    return await service.list_commands(
        status=status_filter,
        device_id=device_id,
        priority=priority,
        command_type=command_type,
        created_after=created_after,
        created_before=created_before,
        offset=offset,
        limit=limit,
        sort=sort,
    )


@router.get("/{command_id}", response_model=CommandDetailDTO)
async def get_command(
    command_id: UUID,
    service: CommandApplicationService = Depends(get_command_application_service),
) -> CommandDetailDTO:
    """Return one command with its terminal result and full event trail."""
    return await service.get_command(command_id)


@router.post("", response_model=CommandDetailDTO, status_code=status.HTTP_201_CREATED)
async def create_command(
    request: CommandCreate,
    service: CommandApplicationService = Depends(get_command_application_service),
) -> CommandDetailDTO:
    """Record a new, immutable command targeting an existing, enabled device."""
    return await service.create_command(request)


@router.post("/{command_id}/cancel", response_model=CommandDetailDTO)
async def cancel_command(
    command_id: UUID,
    body: CancelRequest | None = None,
    service: CommandApplicationService = Depends(get_command_application_service),
) -> CommandDetailDTO:
    """Cancel a command that has not yet reached a terminal state."""
    reason = body.reason if body is not None else None
    return await service.cancel_command(command_id, reason=reason)


@router.delete("/{command_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_command(
    command_id: UUID,
    service: CommandApplicationService = Depends(get_command_application_service),
) -> None:
    """Soft-delete a terminal command from history; still-in-flight commands are rejected."""
    await service.delete_command(command_id)
