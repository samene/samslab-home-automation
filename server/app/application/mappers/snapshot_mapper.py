"""Mapping from Snapshots persistence entities to application DTOs."""

from __future__ import annotations

from app.application.dto.camera_dto import CameraSnapshotDTO
from app.application.dto.snapshot_dto import SnapshotDTO
from app.domains.snapshots.models import Snapshot


def to_snapshot_dto(
    snapshot: Snapshot, *, thumbnail_url: str, image_url: str, workflow_name: str | None = None
) -> SnapshotDTO:
    """Map a persisted snapshot to its DTO, attaching freshly minted presigned URLs."""
    return SnapshotDTO(
        id=snapshot.id,
        device_id=snapshot.device_id,
        command_id=snapshot.command_id,
        filename=snapshot.filename,
        thumbnail_url=thumbnail_url,
        image_url=image_url,
        etag=snapshot.etag,
        sha256=snapshot.sha256,
        width=snapshot.width,
        height=snapshot.height,
        size=snapshot.size,
        captured_at=snapshot.captured_at,
        created_at=snapshot.created_at,
        metadata=snapshot.metadata_,
        workflow_id=snapshot.workflow_id,
        workflow_name=workflow_name,
    )


def to_camera_snapshot_dto(snapshot: Snapshot) -> CameraSnapshotDTO:
    """Map a persisted snapshot to the metadata-only DTO ``POST /camera/snapshot`` returns."""
    return CameraSnapshotDTO(
        id=snapshot.id,
        device_id=snapshot.device_id,
        command_id=snapshot.command_id,
        filename=snapshot.filename,
        width=snapshot.width,
        height=snapshot.height,
        size=snapshot.size,
        captured_at=snapshot.captured_at,
    )
