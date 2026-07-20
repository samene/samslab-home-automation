"""Saved Media data transfer objects: the only shape REST controllers ever see.

Independent of the SQLAlchemy ``SavedMedia`` model. Built exclusively by
``app.application.mappers.saved_media_mapper``. ``thumbnail_url``/
``image_url``/``video_url`` are freshly minted presigned S3 URLs on every
response — never persisted, never stored in PostgreSQL (only the object keys
are); see ``SavedMediaApplicationService``. A row only ever populates the
URL field(s) relevant to its own ``media_type`` — ``image_url`` for IMAGE,
``video_url`` for VIDEO — the other stays ``""``, so the existing Snapshot
Gallery components (which only ever read ``image_url``) keep working
unchanged against IMAGE-filtered data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.domains.saved_media.models import MediaType


class SavedMediaDTO(BaseModel):
    """One image or video's metadata plus fresh, short-lived presigned S3 URLs."""

    id: UUID
    media_type: MediaType
    device_id: UUID
    command_id: UUID
    filename: str
    thumbnail_url: str
    image_url: str
    video_url: str
    etag: str | None
    sha256: str
    width: int
    height: int
    duration: int | None = None
    fps: int | None = None
    bitrate: int | None = None
    size: int
    captured_at: datetime
    created_at: datetime
    metadata: dict[str, Any]
    workflow_id: UUID | None = None
    workflow_name: str | None = None


class SavedMediaPageDTO(BaseModel):
    """A bounded, paginated page of saved media."""

    items: list[SavedMediaDTO]
    total: int
    offset: int
    limit: int
