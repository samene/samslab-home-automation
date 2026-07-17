"""Transactional Device Registry application service and business invariants."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.domains.devices.exceptions import (
    DeviceAlreadyExists,
    DeviceNotFound,
    DuplicateCapability,
    InvalidHeartbeat,
)
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import CapabilityInput, DeviceCreate, DeviceUpdate, HeartbeatInput


class DeviceService:
    """Coordinate Device Registry use cases without exposing persistence details to APIs."""

    def __init__(self, repository: DeviceRepository) -> None:
        """Inject the repository that owns device persistence operations."""
        self._repository = repository

    async def register_device(self, request: DeviceCreate) -> Device:
        """Register a unique logical compute node with its initial capabilities."""
        if await self._repository.find_by_name(request.device_name):
            raise DeviceAlreadyExists(f"Device '{request.device_name}' already exists")
        device = Device(
            device_name=request.device_name,
            hostname=request.hostname,
            display_name=request.display_name,
            description=request.description,
            metadata_=request.metadata,
            status=DeviceStatus.REGISTERING,
        )
        try:
            device = await self._repository.create(device)
            return await self._repository.replace_capabilities(device, request.capabilities)
        except IntegrityError as error:
            raise DeviceAlreadyExists(f"Device '{request.device_name}' already exists") from error

    async def update_device(self, device_id: UUID, request: DeviceUpdate) -> Device:
        """Update administrative device fields without altering heartbeat state."""
        device = await self.get_device(device_id)
        values = request.model_dump(exclude_unset=True)
        if "metadata" in values:
            values["metadata_"] = values.pop("metadata")
        return await self._repository.update(device, values)

    async def heartbeat(self, device_id: UUID, request: HeartbeatInput) -> Device:
        """Record a valid heartbeat while preserving all non-heartbeat attributes."""
        device = await self.get_device(device_id)
        if not device.enabled or device.status is DeviceStatus.DISABLED:
            raise InvalidHeartbeat("Disabled devices cannot send heartbeats")
        if request.status is DeviceStatus.DISABLED:
            raise InvalidHeartbeat("Heartbeat status cannot be DISABLED")
        return await self._repository.update_last_seen(
            device,
            status=request.status,
            agent_version=request.agent_version,
            protocol_version=request.protocol_version,
        )

    async def enable(self, device_id: UUID) -> Device:
        """Enable a device and return it to an unknown state until it heartbeats."""
        device = await self.get_device(device_id)
        return await self._repository.update(
            device, {"enabled": True, "status": DeviceStatus.UNKNOWN}
        )

    async def disable(self, device_id: UUID) -> Device:
        """Disable a device without deleting its history or capability declarations."""
        device = await self.get_device(device_id)
        return await self._repository.update(
            device, {"enabled": False, "status": DeviceStatus.DISABLED}
        )

    async def list_devices(
        self,
        *,
        status: DeviceStatus | None,
        enabled: bool | None,
        capability: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Device], int]:
        """List only active logical devices using repository-owned filtering."""
        return await self._repository.find_all(
            status=status,
            enabled=enabled,
            capability=capability,
            search=search,
            offset=offset,
            limit=limit,
        )

    async def get_device(self, device_id: UUID) -> Device:
        """Return an active device or raise the domain's not-found error."""
        device = await self._repository.find_by_id(device_id)
        if device is None:
            raise DeviceNotFound(f"Device '{device_id}' was not found")
        return device

    async def replace_capabilities(
        self, device_id: UUID, capabilities: list[CapabilityInput]
    ) -> Device:
        """Replace all device capabilities as a single service transaction."""
        device = await self.get_device(device_id)
        names = [capability.capability for capability in capabilities]
        if len(names) != len(set(names)):
            raise DuplicateCapability("Capabilities must not contain duplicate names")
        try:
            return await self._repository.replace_capabilities(device, capabilities)
        except IntegrityError as error:
            raise DuplicateCapability("Capabilities must not contain duplicate names") from error

    async def delete(self, device_id: UUID) -> None:
        """Soft-delete a device so its name and lifecycle remain auditable."""
        device = await self.get_device(device_id)
        await self._repository.delete(device)
