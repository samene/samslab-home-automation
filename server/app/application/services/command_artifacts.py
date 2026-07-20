"""Shared, command-type-aware recording of artifacts a completed command produced.

The one place this knowledge lives, so it's identical regardless of who
created the command. Both ``CameraApplicationService`` (``capture_snapshot``/
``stop_recording``, ``workflow_run_id=None``) and
``WorkflowApplicationService._execute_command_step`` (``workflow_run_id=``
the active run) call ``record_media_from_command`` right after their own
``_wait_for_terminal`` confirms the command completed — never in reaction to
the ``CommandCompleted`` event, which is published *before* the completing
transaction commits (see ``CommandGateway._run``), making a fresh-session
event subscriber racy against an uncommitted write. Adding a future
artifact-producing command type means adding a branch here, not teaching
either caller — least of all the Workflow engine's own step-dispatch logic,
which must stay command-type-agnostic — anything new.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.database import Database
from app.domains.saved_media.models import MediaType, SavedMedia
from app.domains.saved_media.repository import SavedMediaRepository
from app.domains.saved_media.service import SavedMediaService
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.service import WorkflowService

_IMAGE_COMMAND_TYPE = "camera.snapshot"
_VIDEO_COMMAND_TYPE = "camera.record.stop"


async def record_media_from_command(
    database: Database,
    *,
    command_type: str,
    device_id: UUID,
    command_id: UUID,
    result: dict[str, Any],
    workflow_run_id: UUID | None = None,
) -> SavedMedia | None:
    """Persist a completed command's artifact, or no-op if its type doesn't produce one."""
    if command_type not in (_IMAGE_COMMAND_TYPE, _VIDEO_COMMAND_TYPE):
        return None
    async with database.session_factory() as session:
        workflow_id: UUID | None = None
        if workflow_run_id is not None:
            run = await WorkflowService(WorkflowRepository(session)).get_run(workflow_run_id)
            workflow_id = run.workflow_id
        service = SavedMediaService(SavedMediaRepository(session))
        if command_type == _IMAGE_COMMAND_TYPE:
            media = await _record_image(service, device_id, command_id, result, workflow_id, workflow_run_id)
        else:
            media = await _record_video(service, device_id, command_id, result, workflow_id, workflow_run_id)
        await session.commit()
        return media


async def _record_image(
    service: SavedMediaService,
    device_id: UUID,
    command_id: UUID,
    result: dict[str, Any],
    workflow_id: UUID | None,
    workflow_run_id: UUID | None,
) -> SavedMedia:
    return await service.record_media(
        media_type=MediaType.IMAGE,
        device_id=device_id,
        command_id=command_id,
        filename=str(result["filename"]),
        bucket=str(result["bucket"]),
        original_object_key=str(result["original_object_key"]),
        thumbnail_object_key=str(result["thumbnail_object_key"]),
        etag=result.get("etag") if isinstance(result.get("etag"), str) else None,
        sha256=str(result["sha256"]),
        width=int(result["width"]),
        height=int(result["height"]),
        size=int(result["size"]),
        captured_at=_parse_timestamp(result.get("captured_at")) or datetime.now(UTC),
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
    )


async def _record_video(
    service: SavedMediaService,
    device_id: UUID,
    command_id: UUID,
    result: dict[str, Any],
    workflow_id: UUID | None,
    workflow_run_id: UUID | None,
) -> SavedMedia:
    upload_duration = result.get("upload_duration")
    return await service.record_media(
        media_type=MediaType.VIDEO,
        device_id=device_id,
        command_id=command_id,
        filename=str(result["filename"]),
        bucket=str(result["bucket"]),
        original_object_key=str(result["object_key"]),
        thumbnail_object_key=(
            str(result["thumbnail_object_key"])
            if result.get("thumbnail_object_key") is not None
            else None
        ),
        etag=result.get("etag") if isinstance(result.get("etag"), str) else None,
        sha256=str(result["sha256"]),
        width=int(result["width"]),
        height=int(result["height"]),
        duration=int(result["duration"]) if result.get("duration") is not None else None,
        fps=int(result["fps"]) if result.get("fps") is not None else None,
        bitrate=int(result["bitrate"]) if result.get("bitrate") is not None else None,
        size=int(result["file_size"]),
        captured_at=_parse_timestamp(result.get("recorded_at")) or datetime.now(UTC),
        metadata={"upload_duration_seconds": upload_duration} if upload_duration is not None else None,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
    )


def _parse_timestamp(value: object) -> datetime | None:
    """Best-effort parse of a device-reported ISO 8601 timestamp string."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
