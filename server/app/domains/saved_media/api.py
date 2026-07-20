"""FastAPI delivery adapter for Saved Media (images and videos).

Contains no business logic: each route only resolves the application service
and returns the DTO it produces. Presigned S3 URLs are minted fresh on every
``GET`` — never persisted, never hardcoded — so the browser loads
images/videos directly from S3; this layer never proxies media bytes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.application.dto.saved_media_dto import SavedMediaDTO, SavedMediaPageDTO
from app.application.services.saved_media_service import SavedMediaApplicationService
from app.core.database import Database
from app.dependencies import get_database
from app.domains.saved_media.models import MediaType
from app.domains.saved_media.repository import SavedMediaRepository
from app.domains.saved_media.service import SavedMediaService
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.service import WorkflowService

router = APIRouter(prefix="/saved-media", tags=["Saved Media"])

TimeRange = Literal["24h", "3d", "7d", "30d", "90d"]

_RANGE_TIMEDELTAS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _resolve_captured_after(range_value: TimeRange | None) -> datetime | None:
    """Resolve a relative time-range label to an absolute cutoff — the one source of truth
    for what "Last 7 days" means, so the frontend never computes this itself."""
    if range_value is None:
        return None
    return datetime.now(UTC) - _RANGE_TIMEDELTAS[range_value]


async def get_saved_media_application_service(
    request: Request,
    database: Database = Depends(get_database),
) -> AsyncIterator[SavedMediaApplicationService]:
    """Inject a transaction-scoped application service and commit on success only."""
    settings = request.app.state.container.settings()
    async with database.session_factory() as session:
        try:
            yield SavedMediaApplicationService(
                SavedMediaService(SavedMediaRepository(session)),
                s3_client=request.app.state.container.s3_client(),
                presigned_url_ttl_seconds=settings.aws_presigned_url_ttl_seconds,
                workflow_service=WorkflowService(WorkflowRepository(session)),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.get("", response_model=SavedMediaPageDTO)
async def list_saved_media(
    service: SavedMediaApplicationService = Depends(get_saved_media_application_service),
    device_id: UUID | None = Query(default=None),
    media_type: MediaType | None = Query(default=None),
    range: TimeRange | None = Query(default=None),
    offset: int = Query(default=0),
    limit: int = Query(default=50),
) -> SavedMediaPageDTO:
    """List saved media newest-first, with fresh presigned thumbnail/media URLs."""
    return await service.list_media(
        device_id=device_id,
        media_type=media_type,
        captured_after=_resolve_captured_after(range),
        offset=offset,
        limit=limit,
    )


@router.get("/{media_id}", response_model=SavedMediaDTO)
async def get_saved_media(
    media_id: UUID,
    service: SavedMediaApplicationService = Depends(get_saved_media_application_service),
) -> SavedMediaDTO:
    """Return one saved media row with fresh presigned thumbnail/media URLs."""
    return await service.get_media(media_id)


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_media(
    media_id: UUID,
    service: SavedMediaApplicationService = Depends(get_saved_media_application_service),
) -> Response:
    """Delete both S3 objects (best-effort) and hard-delete the metadata row."""
    await service.delete_media(media_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
