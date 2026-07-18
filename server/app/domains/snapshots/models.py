"""SQLAlchemy persistence model owned exclusively by the Snapshots domain.

Unlike Devices/Commands, a snapshot is hard-deleted, not soft-deleted: its
whole point is a real S3 object, so ``DELETE /snapshots/{id}`` removes both
the row and the underlying objects (see ``SnapshotApplicationService``)
rather than preserving an audit trail for a file that no longer exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

json_type = JSON().with_variant(JSONB, "postgresql")


class Snapshot(Base):
    """One captured still image's metadata — never the image bytes themselves."""

    __tablename__ = "snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # No cascade: a snapshot outlives neither domain by construction, but
    # deleting a device/command is not this domain's concern to react to,
    # matching commands.device_id's own no-cascade cross-domain FK.
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("commands.id"), unique=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    bucket: Mapped[str] = mapped_column(String(255))
    original_object_key: Mapped[str] = mapped_column(String(1024))
    thumbnail_object_key: Mapped[str] = mapped_column(String(1024))
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", json_type, default=dict)
    # Both nullable, no cascade — same cross-domain convention as device_id/
    # command_id above. Never null-check-and-orphan on delete: workflows and
    # workflow_runs are only ever soft-deleted by this app's own code, so
    # these FKs never dangle. Populated only for a snapshot captured by a
    # Workflow's Command Task (never for one taken directly from the
    # Dashboard) — see app/application/services/command_artifacts.py.
    workflow_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflows.id"), nullable=True, index=True
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=True, index=True
    )
