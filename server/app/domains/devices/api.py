"""FastAPI delivery adapter for Device Registry administration endpoints.

Contains no business logic: each route only resolves the application
service, forwards validated input to it, and returns the DTO it produces.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.application.dto.device_dto import DeviceDTO, DevicePageDTO
from app.application.events.bus import EventBus
from app.application.services.device_service import DeviceApplicationService
from app.core.database import Database
from app.dependencies import get_database, get_event_bus
from app.domains.devices.models import DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import (
    CapabilityReplace,
    DeviceCreate,
    DeviceUpdate,
    HeartbeatInput,
)
from app.domains.devices.service import DeviceService

router = APIRouter(prefix="/devices", tags=["Devices"])


async def get_device_application_service(
    database: Database = Depends(get_database),
    event_bus: EventBus = Depends(get_event_bus),
) -> AsyncIterator[DeviceApplicationService]:
    """Inject a transaction-scoped application service and commit on success only."""
    async with database.session_factory() as session:
        try:
            yield DeviceApplicationService(DeviceService(DeviceRepository(session)), event_bus)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.get("", response_model=DevicePageDTO)
async def list_devices(
    service: DeviceApplicationService = Depends(get_device_application_service),
    status_filter: DeviceStatus | None = Query(default=None, alias="status"),
    enabled: bool | None = None,
    capability: str | None = Query(default=None, min_length=1, max_length=100),
    search: str | None = Query(default=None, min_length=1, max_length=200),
    offset: int = Query(default=0),
    limit: int = Query(default=50),
) -> DevicePageDTO:
    """List active devices with capability and administrative filters."""
    return await service.list_devices(
        status=status_filter,
        enabled=enabled,
        capability=capability,
        search=search,
        offset=offset,
        limit=limit,
    )


@router.get("/{device_id}", response_model=DeviceDTO)
async def get_device(
    device_id: UUID, service: DeviceApplicationService = Depends(get_device_application_service)
) -> DeviceDTO:
    """Return one active logical device."""
    return await service.get_device(device_id)


@router.post("", response_model=DeviceDTO, status_code=status.HTTP_201_CREATED)
async def register_device(
    request: DeviceCreate,
    service: DeviceApplicationService = Depends(get_device_application_service),
) -> DeviceDTO:
    """Register a logical compute node and its initial capabilities."""
    return await service.register_device(request)


@router.put("/{device_id}", response_model=DeviceDTO)
async def update_device(
    device_id: UUID,
    request: DeviceUpdate,
    service: DeviceApplicationService = Depends(get_device_application_service),
) -> DeviceDTO:
    """Update administrative device metadata."""
    return await service.update_device(device_id, request)


@router.post("/{device_id}/heartbeat", response_model=DeviceDTO)
async def heartbeat(
    device_id: UUID,
    request: HeartbeatInput,
    service: DeviceApplicationService = Depends(get_device_application_service),
) -> DeviceDTO:
    """Record the narrow state update allowed from a heartbeat."""
    return await service.heartbeat(device_id, request)


@router.put("/{device_id}/capabilities", response_model=DeviceDTO)
async def replace_capabilities(
    device_id: UUID,
    request: CapabilityReplace,
    service: DeviceApplicationService = Depends(get_device_application_service),
) -> DeviceDTO:
    """Atomically replace a device's capability declarations."""
    return await service.replace_capabilities(device_id, request.capabilities)


@router.post("/{device_id}/enable", response_model=DeviceDTO)
async def enable(
    device_id: UUID, service: DeviceApplicationService = Depends(get_device_application_service)
) -> DeviceDTO:
    """Enable a device without making hardware contact."""
    return await service.enable(device_id)


@router.post("/{device_id}/disable", response_model=DeviceDTO)
async def disable(
    device_id: UUID, service: DeviceApplicationService = Depends(get_device_application_service)
) -> DeviceDTO:
    """Disable a device without making hardware contact."""
    return await service.disable(device_id)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    device_id: UUID, service: DeviceApplicationService = Depends(get_device_application_service)
) -> Response:
    """Soft-delete a device and return no representation."""
    await service.delete(device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
