"""Snapshot data transfer objects: the only snapshot shape REST controllers ever see.

Independent of the SQLAlchemy ``Snapshot`` model. Built exclusively by
``app.application.mappers.snapshot_mapper``. ``thumbnail_url``/``image_url``
are freshly minted presigned S3 URLs on every response — never persisted,
never stored in PostgreSQL (only the object keys are); see
``SnapshotApplicationService``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SnapshotDTO(BaseModel):
    """One snapshot's metadata plus fresh, short-lived presigned S3 URLs."""

    id: UUID
    device_id: UUID
    command_id: UUID
    filename: str
    thumbnail_url: str
    image_url: str
    etag: str | None
    sha256: str
    width: int
    height: int
    size: int
    captured_at: datetime
    created_at: datetime
    metadata: dict[str, Any]
    # Both null unless this snapshot was captured by a Workflow's Command
    # Task — workflow_name is resolved fresh on every read (never persisted
    # alongside it) so a later workflow rename is reflected immediately, and
    # still resolves even after the workflow itself has been (soft-)deleted.
    workflow_id: UUID | None = None
    workflow_name: str | None = None


class SnapshotPageDTO(BaseModel):
    """A bounded, paginated page of snapshots."""

    items: list[SnapshotDTO]
    total: int
    offset: int
    limit: int
