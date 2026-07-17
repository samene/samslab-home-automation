"""Device data transfer objects: the only device shape REST controllers ever see.

Independent of both the SQLAlchemy ``Device``/``DeviceCapability`` models and
of the devices domain's own ``schemas.py`` response models. Built exclusively
by ``app.application.mappers.device_mapper``, never by validating a
persistence entity via ``from_attributes``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.domains.devices.models import DeviceStatus


class CapabilityDTO(BaseModel):
    """One capability declared by a device."""

    id: UUID
    capability: str
    version: str
    configuration: dict[str, Any]


class DeviceDTO(BaseModel):
    """A logical device and its declared capabilities."""

    id: UUID
    device_name: str
    hostname: str
    display_name: str
    description: str | None
    status: DeviceStatus
    last_seen: datetime | None
    agent_version: str | None
    protocol_version: str | None
    registered_at: datetime
    updated_at: datetime
    enabled: bool
    metadata: dict[str, Any]
    capabilities: list[CapabilityDTO]


class DevicePageDTO(BaseModel):
    """A bounded, paginated page of devices."""

    items: list[DeviceDTO]
    total: int
    offset: int
    limit: int
