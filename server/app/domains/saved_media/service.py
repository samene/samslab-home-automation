"""Transactional Saved Media application service and business invariants."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.domains.saved_media.exceptions import SavedMediaNotFound
from app.domains.saved_media.models import MediaType, SavedMedia
from app.domains.saved_media.repository import SavedMediaRepository


class SavedMediaService:
    """Coordinate Saved Media use cases without exposing persistence details to APIs."""

    def __init__(self, repository: SavedMediaRepository) -> None:
        """Inject the repository that owns saved media persistence operations."""
        self._repository = repository

    async def record_media(
        self,
        *,
        media_type: MediaType,
        device_id: UUID,
        command_id: UUID,
        filename: str,
        bucket: str,
        original_object_key: str,
        thumbnail_object_key: str | None,
        etag: str | None,
        sha256: str,
        width: int,
        height: int,
        size: int,
        captured_at: datetime,
        duration: int | None = None,
        fps: int | None = None,
        bitrate: int | None = None,
        metadata: dict[str, Any] | None = None,
        workflow_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
    ) -> SavedMedia:
        """Persist metadata for one already-uploaded image or video; never touches S3.

        ``workflow_id``/``workflow_run_id`` are set only when this row was
        captured by a Workflow's Command Task rather than directly from the
        Dashboard — see ``app/application/services/command_artifacts.py``.
        ``duration``/``fps``/``bitrate`` are always ``None`` for
        ``media_type=IMAGE``; ``thumbnail_object_key`` is always ``None`` for
        ``media_type=VIDEO`` (no thumbnail generation yet).
        """
        media = SavedMedia(
            media_type=media_type,
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
            duration=duration,
            fps=fps,
            bitrate=bitrate,
            size=size,
            captured_at=captured_at,
            metadata_=metadata or {},
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )
        return await self._repository.create(media)

    async def get_media(self, media_id: UUID) -> SavedMedia:
        """Return one saved media row or raise the domain's not-found error."""
        media = await self._repository.find_by_id(media_id)
        if media is None:
            raise SavedMediaNotFound(f"Saved media '{media_id}' was not found")
        return media

    async def list_media(
        self,
        *,
        device_id: UUID | None,
        media_type: MediaType | None,
        captured_after: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SavedMedia], int]:
        """List saved media newest-first, optionally scoped by device/type/time window."""
        return await self._repository.find_all(
            device_id=device_id,
            media_type=media_type,
            captured_after=captured_after,
            offset=offset,
            limit=limit,
        )

    async def find_by_workflow_id(self, workflow_id: UUID) -> list[SavedMedia]:
        """Return every saved media row a given workflow's runs have ever produced."""
        return await self._repository.find_by_workflow_id(workflow_id)

    async def delete_media(self, media_id: UUID) -> SavedMedia:
        """Hard-delete a saved media row, returning the deleted entity for S3 cleanup."""
        media = await self.get_media(media_id)
        await self._repository.delete(media)
        return media
