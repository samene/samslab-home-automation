"""SQLAlchemy persistence models owned exclusively by the Device Registry domain."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DeviceStatus(StrEnum):
    """Lifecycle state reported for a logical compute node."""

    REGISTERING = "REGISTERING"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNHEALTHY = "UNHEALTHY"
    DISCONNECTED = "DISCONNECTED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


json_type = JSON().with_variant(JSONB, "postgresql")


class Device(Base):
    """A logical compute node, independent of any particular hardware type."""

    __tablename__ = "devices"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(253), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False, length=20),
        default=DeviceStatus.REGISTERING,
        index=True,
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    agent_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", json_type, default=dict)
    capabilities: Mapped[list[DeviceCapability]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )


class DeviceCapability(Base):
    """A versioned string capability declared by a device."""

    __tablename__ = "device_capabilities"
    __table_args__ = (
        UniqueConstraint("device_id", "capability", name="uq_device_capabilities_device"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    capability: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(100))
    configuration: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)
    device: Mapped[Device] = relationship(back_populates="capabilities")
