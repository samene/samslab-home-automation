"""Application service wrapping Device Registry use cases for REST controllers."""

from __future__ import annotations

from uuid import UUID

from app.application.dto.device_dto import DeviceDTO, DevicePageDTO
from app.application.events.bus import EventBus
from app.application.events.domain_events import DeviceHeartbeat, DeviceRegistered
from app.application.exceptions import translate_domain_error
from app.application.mappers.device_mapper import to_device_dto
from app.application.validators import PaginationParams
from app.domains.devices.exceptions import DeviceDomainError
from app.domains.devices.models import DeviceStatus
from app.domains.devices.schemas import (
    CapabilityInput,
    DeviceCreate,
    DeviceUpdate,
    HeartbeatInput,
)
from app.domains.devices.service import DeviceService


class DeviceApplicationService:
    """Expose Device Registry use cases as DTOs, translating domain failures."""

    def __init__(self, device_service: DeviceService, event_bus: EventBus) -> None:
        """Wrap the domain service; publish lifecycle events on the shared event bus."""
        self._devices = device_service
        self._event_bus = event_bus

    async def register_device(self, request: DeviceCreate) -> DeviceDTO:
        """Validate, register, and return the newly created device."""
        try:
            device = await self._devices.register_device(request)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        await self._event_bus.publish(
            DeviceRegistered(
                device_id=device.id,
                device_name=device.device_name,
                occurred_at=device.registered_at,
            )
        )
        return to_device_dto(device)

    async def get_device(self, device_id: UUID) -> DeviceDTO:
        """Return one active device."""
        try:
            device = await self._devices.get_device(device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_dto(device)

    async def list_devices(
        self,
        *,
        status: DeviceStatus | None,
        enabled: bool | None,
        capability: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> DevicePageDTO:
        """List devices with bounded, centrally validated pagination."""
        pagination = PaginationParams.create(offset=offset, limit=limit)
        devices, total = await self._devices.list_devices(
            status=status,
            enabled=enabled,
            capability=capability,
            search=search,
            offset=pagination.offset,
            limit=pagination.limit,
        )
        return DevicePageDTO(
            items=[to_device_dto(device) for device in devices],
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    async def update_device(self, device_id: UUID, request: DeviceUpdate) -> DeviceDTO:
        """Update administrative device metadata."""
        try:
            device = await self._devices.update_device(device_id, request)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_dto(device)

    async def heartbeat(self, device_id: UUID, request: HeartbeatInput) -> DeviceDTO:
        """Record a device heartbeat and publish a ``DeviceHeartbeat`` event."""
        try:
            device = await self._devices.heartbeat(device_id, request)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        assert device.last_seen is not None  # a successful heartbeat always sets this
        await self._event_bus.publish(
            DeviceHeartbeat(
                device_id=device.id, status=device.status.value, occurred_at=device.last_seen
            )
        )
        return to_device_dto(device)

    async def enable(self, device_id: UUID) -> DeviceDTO:
        """Re-enable a device."""
        try:
            device = await self._devices.enable(device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_dto(device)

    async def disable(self, device_id: UUID) -> DeviceDTO:
        """Disable a device."""
        try:
            device = await self._devices.disable(device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_dto(device)

    async def replace_capabilities(
        self, device_id: UUID, capabilities: list[CapabilityInput]
    ) -> DeviceDTO:
        """Atomically replace a device's declared capabilities."""
        try:
            device = await self._devices.replace_capabilities(device_id, capabilities)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_dto(device)

    async def delete(self, device_id: UUID) -> None:
        """Soft-delete a device."""
        try:
            await self._devices.delete(device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
