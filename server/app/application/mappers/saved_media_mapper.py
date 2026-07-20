"""Mapping from Saved Media persistence entities to application DTOs."""

from __future__ import annotations

from app.application.dto.camera_dto import CameraRecordingDTO, CameraSnapshotDTO
from app.application.dto.saved_media_dto import SavedMediaDTO
from app.domains.saved_media.models import MediaType, SavedMedia


def to_saved_media_dto(
    media: SavedMedia, *, thumbnail_url: str, media_url: str, workflow_name: str | None = None
) -> SavedMediaDTO:
    """Map a persisted saved media row to its DTO, attaching freshly minted presigned URLs.

    ``media_url`` is the one presigned URL for the row's own object (the
    "original" image, or the video file) — routed into ``image_url`` for
    IMAGE rows and ``video_url`` for VIDEO rows, so existing IMAGE-only
    consumers (the Snapshot Gallery) keep reading ``image_url`` unchanged.
    """
    return SavedMediaDTO(
        id=media.id,
        media_type=media.media_type,
        device_id=media.device_id,
        command_id=media.command_id,
        filename=media.filename,
        thumbnail_url=thumbnail_url,
        image_url=media_url if media.media_type is MediaType.IMAGE else "",
        video_url=media_url if media.media_type is MediaType.VIDEO else "",
        etag=media.etag,
        sha256=media.sha256,
        width=media.width,
        height=media.height,
        duration=media.duration,
        fps=media.fps,
        bitrate=media.bitrate,
        size=media.size,
        captured_at=media.captured_at,
        created_at=media.created_at,
        metadata=media.metadata_,
        workflow_id=media.workflow_id,
        workflow_name=workflow_name,
    )


def to_camera_snapshot_dto(media: SavedMedia) -> CameraSnapshotDTO:
    """Map a persisted IMAGE row to the metadata-only DTO ``POST /camera/snapshot`` returns."""
    return CameraSnapshotDTO(
        id=media.id,
        device_id=media.device_id,
        command_id=media.command_id,
        filename=media.filename,
        width=media.width,
        height=media.height,
        size=media.size,
        captured_at=media.captured_at,
    )


def to_camera_recording_dto(
    media: SavedMedia, *, upload_duration_seconds: float
) -> CameraRecordingDTO:
    """Map a persisted VIDEO row to the metadata-only DTO ``POST /camera/record/stop`` returns."""
    assert media.duration is not None  # always set for a VIDEO row
    return CameraRecordingDTO(
        id=media.id,
        bucket=media.bucket,
        object_key=media.original_object_key,
        etag=media.etag,
        sha256=media.sha256,
        filename=media.filename,
        duration_seconds=media.duration,
        width=media.width,
        height=media.height,
        fps=media.fps,
        bitrate=media.bitrate,
        file_size=media.size,
        recorded_at=media.captured_at,
        upload_duration_seconds=upload_duration_seconds,
    )
