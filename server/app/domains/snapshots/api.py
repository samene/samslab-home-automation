"""FastAPI delivery adapter for the Snapshot Gallery.

Contains no business logic: each route only resolves the application service
and returns the DTO it produces. Presigned S3 URLs are minted fresh on every
``GET`` — never persisted, never hardcoded — so the browser loads images
directly from S3; this layer never proxies image bytes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.application.dto.snapshot_dto import SnapshotDTO, SnapshotPageDTO
from app.application.services.snapshot_service import SnapshotApplicationService
from app.core.database import Database
from app.dependencies import get_database
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService

router = APIRouter(prefix="/snapshots", tags=["Snapshots"])


async def get_snapshot_application_service(
    request: Request,
    database: Database = Depends(get_database),
) -> AsyncIterator[SnapshotApplicationService]:
    """Inject a transaction-scoped application service and commit on success only."""
    settings = request.app.state.container.settings()
    async with database.session_factory() as session:
        try:
            yield SnapshotApplicationService(
                SnapshotService(SnapshotRepository(session)),
                s3_client=request.app.state.container.s3_client(),
                presigned_url_ttl_seconds=settings.aws_presigned_url_ttl_seconds,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.get("", response_model=SnapshotPageDTO)
async def list_snapshots(
    service: SnapshotApplicationService = Depends(get_snapshot_application_service),
    device_id: UUID | None = Query(default=None),
    offset: int = Query(default=0),
    limit: int = Query(default=50),
) -> SnapshotPageDTO:
    """List snapshots newest-first, with fresh presigned thumbnail/image URLs."""
    return await service.list_snapshots(device_id=device_id, offset=offset, limit=limit)


@router.get("/{snapshot_id}", response_model=SnapshotDTO)
async def get_snapshot(
    snapshot_id: UUID,
    service: SnapshotApplicationService = Depends(get_snapshot_application_service),
) -> SnapshotDTO:
    """Return one snapshot with fresh presigned thumbnail/image URLs."""
    return await service.get_snapshot(snapshot_id)


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snapshot(
    snapshot_id: UUID,
    service: SnapshotApplicationService = Depends(get_snapshot_application_service),
) -> Response:
    """Delete both S3 objects (best-effort) and hard-delete the metadata row."""
    await service.delete_snapshot(snapshot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
