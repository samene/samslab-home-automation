"""Typed API contracts and validation rules for the Device Registry domain."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.devices.models import DeviceStatus

DEVICE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,99}$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]$|^[a-zA-Z0-9]$"
)
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,99}$")


class CapabilityInput(BaseModel):
    """An extensible capability declaration; capability names deliberately are not enums."""

    capability: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(min_length=1, max_length=100)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        """Accept portable version labels while preventing ambiguous whitespace values."""
        if not VERSION_PATTERN.fullmatch(value):
            raise ValueError("version contains unsupported characters")
        return value


class DeviceCreate(BaseModel):
    """Input for registering a logical compute node."""

    device_name: str = Field(min_length=2, max_length=100)
    hostname: str = Field(min_length=1, max_length=253)
    display_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[CapabilityInput] = Field(default_factory=list)

    @field_validator("device_name")
    @classmethod
    def validate_device_name(cls, value: str) -> str:
        """Require a stable DNS-label-like logical device name."""
        if not DEVICE_NAME_PATTERN.fullmatch(value):
            raise ValueError("device_name must be lowercase letters, digits, and hyphens")
        return value

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        """Reject malformed hostnames before persistence."""
        if not HOSTNAME_PATTERN.fullmatch(value):
            raise ValueError("hostname must be a valid hostname")
        return value.lower()

    @field_validator("capabilities")
    @classmethod
    def reject_duplicate_capabilities(cls, value: list[CapabilityInput]) -> list[CapabilityInput]:
        """Keep capability replacement deterministic at the API boundary."""
        names = [item.capability for item in value]
        if len(names) != len(set(names)):
            raise ValueError("capabilities must not contain duplicates")
        return value


class DeviceUpdate(BaseModel):
    """Mutable device attributes; heartbeat fields remain on their dedicated endpoint."""

    hostname: str | None = Field(default=None, min_length=1, max_length=253)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    metadata: dict[str, Any] | None = None

    @field_validator("hostname")
    @classmethod
    def validate_optional_hostname(cls, value: str | None) -> str | None:
        """Validate hostname when the caller elects to change it."""
        if value is not None and not HOSTNAME_PATTERN.fullmatch(value):
            raise ValueError("hostname must be a valid hostname")
        return value.lower() if value else value


class HeartbeatInput(BaseModel):
    """The limited state transition accepted from a device heartbeat."""

    status: DeviceStatus
    agent_version: str = Field(min_length=1, max_length=100)
    protocol_version: str = Field(min_length=1, max_length=100)

    @field_validator("agent_version", "protocol_version")
    @classmethod
    def validate_versions(cls, value: str) -> str:
        """Require unambiguous version identifiers."""
        if not VERSION_PATTERN.fullmatch(value):
            raise ValueError("version contains unsupported characters")
        return value


class CapabilityReplace(BaseModel):
    """Complete, atomic replacement of the device capability set."""

    capabilities: list[CapabilityInput]

    @field_validator("capabilities")
    @classmethod
    def reject_duplicate_capabilities(cls, value: list[CapabilityInput]) -> list[CapabilityInput]:
        """Reject duplicates before a transaction begins."""
        names = [item.capability for item in value]
        if len(names) != len(set(names)):
            raise ValueError("capabilities must not contain duplicates")
        return value


class CapabilityResponse(CapabilityInput):
    """Persisted capability representation."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID


class DeviceResponse(BaseModel):
    """Public representation of a logical device and its declared capabilities."""

    model_config = ConfigDict(from_attributes=True)

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
    capabilities: list[CapabilityResponse]


class DevicePage(BaseModel):
    """Cursor-free bounded pagination response for initial registry administration."""

    items: list[DeviceResponse]
    total: int
    offset: int
    limit: int
