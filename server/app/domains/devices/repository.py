"""SQLAlchemy repository implementing all Device Registry persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.devices.models import Device, DeviceCapability, DeviceStatus
from app.domains.devices.schemas import CapabilityInput


class DeviceRepository:
    """Persist and query devices without leaking SQLAlchemy into application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    @staticmethod
    def _active_devices() -> Select[tuple[Device]]:
        """Build the common active-device query with capabilities preloaded."""
        return (
            select(Device)
            .options(selectinload(Device.capabilities))
            .where(Device.deleted_at.is_(None))
        )

    async def create(self, device: Device) -> Device:
        """Stage a new device for commit by the application service."""
        self._session.add(device)
        await self._session.flush()
        await self._session.refresh(device, attribute_names=["capabilities"])
        return device

    async def update(self, device: Device, values: dict[str, object]) -> Device:
        """Apply explicitly approved mutable values to a device."""
        for name, value in values.items():
            setattr(device, name, value)
        await self._session.flush()
        await self._session.refresh(device)
        return device

    async def delete(self, device: Device) -> None:
        """Soft-delete a device while preserving auditability and uniqueness history."""
        device.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def find_by_id(self, device_id: UUID) -> Device | None:
        """Find one active device by UUID."""
        result = await self._session.execute(self._active_devices().where(Device.id == device_id))
        return result.scalar_one_or_none()

    async def find_by_name(self, device_name: str) -> Device | None:
        """Find one active device by its unique logical name."""
        result = await self._session.execute(
            self._active_devices().where(Device.device_name == device_name)
        )
        return result.scalar_one_or_none()

    async def find_all(
        self,
        *,
        status: DeviceStatus | None,
        enabled: bool | None,
        capability: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Device], int]:
        """List active devices with bounded filtering and pagination."""
        filters: list[ColumnElement[bool]] = [Device.deleted_at.is_(None)]
        if status is not None:
            filters.append(Device.status == status)
        if enabled is not None:
            filters.append(Device.enabled.is_(enabled))
        if capability is not None:
            filters.append(Device.capabilities.any(DeviceCapability.capability == capability))
        if search:
            term = f"%{search.strip()}%"
            filters.append(or_(Device.device_name.ilike(term), Device.display_name.ilike(term)))
        count = await self._session.scalar(select(func.count(Device.id)).where(*filters))
        result = await self._session.execute(
            select(Device)
            .options(selectinload(Device.capabilities))
            .where(*filters)
            .order_by(Device.device_name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().unique()), count or 0

    async def update_last_seen(
        self, device: Device, *, status: DeviceStatus, agent_version: str, protocol_version: str
    ) -> Device:
        """Apply the only fields allowed to change through a heartbeat."""
        device.last_seen = datetime.now(UTC)
        device.status = status
        device.agent_version = agent_version
        device.protocol_version = protocol_version
        await self._session.flush()
        await self._session.refresh(device)
        return device

    async def replace_capabilities(
        self, device: Device, capabilities: list[CapabilityInput]
    ) -> Device:
        """Atomically replace all capability rows through the caller transaction."""
        device.capabilities.clear()
        await self._session.flush()
        device.capabilities.extend(
            DeviceCapability(
                capability=item.capability,
                version=item.version,
                configuration=item.configuration,
            )
            for item in capabilities
        )
        await self._session.flush()
        await self._session.refresh(device, attribute_names=["capabilities"])
        return device
