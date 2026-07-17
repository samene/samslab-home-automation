"""Mapping from Device Registry persistence entities to application DTOs."""

from __future__ import annotations

from app.application.dto.device_dto import CapabilityDTO, DeviceDTO
from app.domains.devices.models import Device, DeviceCapability


def to_capability_dto(capability: DeviceCapability) -> CapabilityDTO:
    """Map one persisted capability row to its DTO."""
    return CapabilityDTO(
        id=capability.id,
        capability=capability.capability,
        version=capability.version,
        configuration=capability.configuration,
    )


def to_device_dto(device: Device) -> DeviceDTO:
    """Map a persisted device, and its capabilities, to a application DTO."""
    return DeviceDTO(
        id=device.id,
        device_name=device.device_name,
        hostname=device.hostname,
        display_name=device.display_name,
        description=device.description,
        status=device.status,
        last_seen=device.last_seen,
        agent_version=device.agent_version,
        protocol_version=device.protocol_version,
        registered_at=device.registered_at,
        updated_at=device.updated_at,
        enabled=device.enabled,
        metadata=device.metadata_,
        capabilities=[to_capability_dto(capability) for capability in device.capabilities],
    )
