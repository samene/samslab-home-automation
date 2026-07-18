"""Transactional Snapshots application service and business invariants."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.domains.snapshots.exceptions import SnapshotNotFound
from app.domains.snapshots.models import Snapshot
from app.domains.snapshots.repository import SnapshotRepository


class SnapshotService:
    """Coordinate Snapshots use cases without exposing persistence details to APIs."""

    def __init__(self, repository: SnapshotRepository) -> None:
        """Inject the repository that owns snapshot persistence operations."""
        self._repository = repository

    async def record_snapshot(
        self,
        *,
        device_id: UUID,
        command_id: UUID,
        filename: str,
        bucket: str,
        original_object_key: str,
        thumbnail_object_key: str,
        etag: str | None,
        sha256: str,
        width: int,
        height: int,
        size: int,
        captured_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> Snapshot:
        """Persist metadata for one already-uploaded snapshot; never touches S3."""
        snapshot = Snapshot(
            device_id=device_id,
            command_id=command_id,
            filename=filename,
            bucket=bucket,
            original_object_key=original_object_key,
            thumbnail_object_key=thumbnail_object_key,
            etag=etag,
            sha256=sha256,
            width=width,
            height=height,
            size=size,
            captured_at=captured_at,
            metadata_=metadata or {},
        )
        return await self._repository.create(snapshot)

    async def get_snapshot(self, snapshot_id: UUID) -> Snapshot:
        """Return one snapshot or raise the domain's not-found error."""
        snapshot = await self._repository.find_by_id(snapshot_id)
        if snapshot is None:
            raise SnapshotNotFound(f"Snapshot '{snapshot_id}' was not found")
        return snapshot

    async def list_snapshots(
        self, *, device_id: UUID | None, offset: int, limit: int
    ) -> tuple[list[Snapshot], int]:
        """List snapshots newest-first, optionally scoped to one device."""
        return await self._repository.find_all(device_id=device_id, offset=offset, limit=limit)

    async def delete_snapshot(self, snapshot_id: UUID) -> Snapshot:
        """Hard-delete a snapshot row, returning the deleted entity for S3 cleanup."""
        snapshot = await self.get_snapshot(snapshot_id)
        await self._repository.delete(snapshot)
        return snapshot
