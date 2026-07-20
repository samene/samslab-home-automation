"""Application service wrapping Saved Media use cases for REST controllers.

The only place a presigned S3 URL is ever minted (list/get) or an S3 object
ever deleted — ``CameraApplicationService.capture_snapshot``/``stop_recording``
only persist metadata via the domain's own ``SavedMediaService`` and never
touch this adapter. See ``app/core/s3_client.py``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

import structlog

from app.application.dto.saved_media_dto import SavedMediaDTO, SavedMediaPageDTO
from app.application.exceptions import translate_domain_error
from app.application.mappers.saved_media_mapper import to_saved_media_dto
from app.application.validators import PaginationParams
from app.core.s3_client import S3Client
from app.domains.saved_media.exceptions import SavedMediaDomainError
from app.domains.saved_media.models import MediaType, SavedMedia
from app.domains.saved_media.service import SavedMediaService
from app.domains.workflows.service import WorkflowService

logger = structlog.get_logger(__name__)


class SavedMediaApplicationService:
    """Expose Saved Media use cases as DTOs, translating domain failures."""

    def __init__(
        self,
        saved_media_service: SavedMediaService,
        *,
        s3_client: S3Client | None,
        presigned_url_ttl_seconds: float,
        workflow_service: WorkflowService | None = None,
    ) -> None:
        """Wrap the domain service; ``s3_client`` is None when S3 isn't configured.

        ``workflow_service`` is optional and used only to resolve a
        workflow-captured row's originating workflow name for display —
        omit it (e.g. when this service is built just to delete rows as part
        of deleting their workflow/schedule) and names simply won't resolve.
        """
        self._media = saved_media_service
        self._s3_client = s3_client
        self._presigned_url_ttl_seconds = presigned_url_ttl_seconds
        self._workflows = workflow_service

    async def get_media(self, media_id: UUID) -> SavedMediaDTO:
        """Return one saved media row with freshly minted presigned URLs."""
        try:
            media = await self._media.get_media(media_id)
        except SavedMediaDomainError as error:
            raise translate_domain_error(error) from error
        workflow_names = await self._resolve_workflow_names([media])
        return self._to_dto(media, workflow_names)

    async def list_media(
        self,
        *,
        device_id: UUID | None,
        media_type: MediaType | None,
        captured_after: datetime | None,
        offset: int,
        limit: int,
    ) -> SavedMediaPageDTO:
        """List saved media newest-first with bounded, centrally validated pagination."""
        pagination = PaginationParams.create(offset=offset, limit=limit)
        items, total = await self._media.list_media(
            device_id=device_id,
            media_type=media_type,
            captured_after=captured_after,
            offset=pagination.offset,
            limit=pagination.limit,
        )
        workflow_names = await self._resolve_workflow_names(items)
        return SavedMediaPageDTO(
            items=[self._to_dto(item, workflow_names) for item in items],
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    async def _resolve_workflow_names(self, items: list[SavedMedia]) -> dict[UUID, str]:
        """Batch-resolve every distinct workflow_id across a page of items, one query."""
        if self._workflows is None:
            return {}
        workflow_ids = {item.workflow_id for item in items if item.workflow_id}
        if not workflow_ids:
            return {}
        return await self._workflows.get_workflow_names(list(workflow_ids))

    async def delete_media(self, media_id: UUID) -> None:
        """Delete S3 object(s) (best-effort) then hard-delete the metadata row."""
        try:
            media = await self._media.get_media(media_id)
        except SavedMediaDomainError as error:
            raise translate_domain_error(error) from error
        await self._delete_from_s3(media)
        try:
            await self._media.delete_media(media_id)
        except SavedMediaDomainError as error:
            raise translate_domain_error(error) from error

    async def _delete_from_s3(self, media: SavedMedia) -> None:
        """Best-effort: an S3 failure or missing configuration never blocks the DB delete."""
        if self._s3_client is None:
            logger.warning("saved_media_delete_skipped_s3_unconfigured", media_id=str(media.id))
            return
        loop = asyncio.get_running_loop()
        object_keys = [media.original_object_key]
        if media.thumbnail_object_key is not None:
            object_keys.append(media.thumbnail_object_key)
        for object_key in object_keys:
            try:
                await loop.run_in_executor(None, self._s3_client.delete_object, object_key)
            except Exception as error:
                logger.warning(
                    "saved_media_s3_delete_failed",
                    media_id=str(media.id),
                    object_key=object_key,
                    error=str(error),
                )

    def _to_dto(self, media: SavedMedia, workflow_names: dict[UUID, str]) -> SavedMediaDTO:
        workflow_name = (
            workflow_names.get(media.workflow_id) if media.workflow_id is not None else None
        )
        return to_saved_media_dto(
            media,
            thumbnail_url=self._presigned_url(media.thumbnail_object_key),
            media_url=self._presigned_url(media.original_object_key),
            workflow_name=workflow_name,
        )

    def _presigned_url(self, object_key: str | None) -> str:
        """A fresh, short-lived presigned URL, or "" when unset/S3 isn't configured."""
        if object_key is None or self._s3_client is None:
            return ""
        return self._s3_client.generate_presigned_url(
            object_key, ttl_seconds=self._presigned_url_ttl_seconds
        )
