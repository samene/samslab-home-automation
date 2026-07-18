"""Application service wrapping Snapshots use cases for REST controllers.

The only place a presigned S3 URL is ever minted (list/get) or an S3 object
ever deleted — ``CameraApplicationService.capture_snapshot`` only persists
metadata via the domain's own ``SnapshotService`` and never touches this
adapter. See ``app/core/s3_client.py``.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog

from app.application.dto.snapshot_dto import SnapshotDTO, SnapshotPageDTO
from app.application.exceptions import translate_domain_error
from app.application.mappers.snapshot_mapper import to_snapshot_dto
from app.application.validators import PaginationParams
from app.core.s3_client import S3Client
from app.domains.snapshots.exceptions import SnapshotDomainError
from app.domains.snapshots.models import Snapshot
from app.domains.snapshots.service import SnapshotService

logger = structlog.get_logger(__name__)


class SnapshotApplicationService:
    """Expose Snapshots use cases as DTOs, translating domain failures."""

    def __init__(
        self,
        snapshot_service: SnapshotService,
        *,
        s3_client: S3Client | None,
        presigned_url_ttl_seconds: float,
    ) -> None:
        """Wrap the domain service; ``s3_client`` is None when S3 isn't configured."""
        self._snapshots = snapshot_service
        self._s3_client = s3_client
        self._presigned_url_ttl_seconds = presigned_url_ttl_seconds

    async def get_snapshot(self, snapshot_id: UUID) -> SnapshotDTO:
        """Return one snapshot with freshly minted presigned URLs."""
        try:
            snapshot = await self._snapshots.get_snapshot(snapshot_id)
        except SnapshotDomainError as error:
            raise translate_domain_error(error) from error
        return self._to_dto(snapshot)

    async def list_snapshots(
        self, *, device_id: UUID | None, offset: int, limit: int
    ) -> SnapshotPageDTO:
        """List snapshots newest-first with bounded, centrally validated pagination."""
        pagination = PaginationParams.create(offset=offset, limit=limit)
        snapshots, total = await self._snapshots.list_snapshots(
            device_id=device_id, offset=pagination.offset, limit=pagination.limit
        )
        return SnapshotPageDTO(
            items=[self._to_dto(snapshot) for snapshot in snapshots],
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    async def delete_snapshot(self, snapshot_id: UUID) -> None:
        """Delete both S3 objects (best-effort) then hard-delete the metadata row."""
        try:
            snapshot = await self._snapshots.get_snapshot(snapshot_id)
        except SnapshotDomainError as error:
            raise translate_domain_error(error) from error
        await self._delete_from_s3(snapshot)
        try:
            await self._snapshots.delete_snapshot(snapshot_id)
        except SnapshotDomainError as error:
            raise translate_domain_error(error) from error

    async def _delete_from_s3(self, snapshot: Snapshot) -> None:
        """Best-effort: an S3 failure or missing configuration never blocks the DB delete."""
        if self._s3_client is None:
            logger.warning(
                "snapshot_delete_skipped_s3_unconfigured", snapshot_id=str(snapshot.id)
            )
            return
        loop = asyncio.get_running_loop()
        for object_key in (snapshot.original_object_key, snapshot.thumbnail_object_key):
            try:
                await loop.run_in_executor(None, self._s3_client.delete_object, object_key)
            except Exception as error:
                logger.warning(
                    "snapshot_s3_delete_failed",
                    snapshot_id=str(snapshot.id),
                    object_key=object_key,
                    error=str(error),
                )

    def _to_dto(self, snapshot: Snapshot) -> SnapshotDTO:
        return to_snapshot_dto(
            snapshot,
            thumbnail_url=self._presigned_url(snapshot.thumbnail_object_key),
            image_url=self._presigned_url(snapshot.original_object_key),
        )

    def _presigned_url(self, object_key: str) -> str:
        """A fresh, short-lived presigned URL, or an empty string when S3 isn't configured."""
        if self._s3_client is None:
            return ""
        return self._s3_client.generate_presigned_url(
            object_key, ttl_seconds=self._presigned_url_ttl_seconds
        )
