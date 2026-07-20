"""SQLAlchemy persistence model owned exclusively by the Saved Media domain.

Generalizes what was originally a snapshot-only ``snapshots`` table: one row
now describes either a still image (``media_type=IMAGE``, produced by a
completed ``camera.snapshot`` command) or a video recording
(``media_type=VIDEO``, produced by a completed ``camera.record.stop``
command) — the same agent-captures-and-uploads-directly-to-S3,
server-persists-metadata-only shape either way, so one table serves both
rather than two near-identical implementations. Video-only fields
(``duration``/``fps``/``bitrate``) are nullable and stay ``None`` for images;
``thumbnail_object_key`` is nullable since video thumbnail generation isn't
implemented yet (the frontend renders a placeholder in that case).

Unlike Devices/Commands, a row is hard-deleted, not soft-deleted: its whole
point is a real S3 object, so ``DELETE /saved-media/{id}`` removes both the
row and the underlying object(s) (see ``SavedMediaApplicationService``)
rather than preserving an audit trail for a file that no longer exists.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

json_type = JSON().with_variant(JSONB, "postgresql")


class MediaType(StrEnum):
    """What kind of file one Saved Media row describes."""

    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class SavedMedia(Base):
    """One agent-captured file's metadata — never the image/video bytes themselves."""

    __tablename__ = "saved_media"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, native_enum=False, length=20), index=True
    )
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("commands.id"), unique=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    bucket: Mapped[str] = mapped_column(String(255))
    original_object_key: Mapped[str] = mapped_column(String(1024))
    # Null for every VIDEO row — thumbnail generation isn't implemented this
    # phase; the frontend renders a placeholder when absent.
    thumbnail_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Video-only, nullable — always None for an IMAGE row.
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", json_type, default=dict)
    workflow_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflows.id"), nullable=True, index=True
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=True, index=True
    )
