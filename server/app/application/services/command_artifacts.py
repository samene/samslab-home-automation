"""Shared, command-type-aware recording of artifacts a completed command produced.

The one place this knowledge lives, so it's identical regardless of who
created the command. Both ``CameraApplicationService.capture_snapshot``
(``workflow_run_id=None``) and ``WorkflowApplicationService._execute_command_step``
(``workflow_run_id=`` the active run) call ``record_snapshot_from_command``
right after their own ``_wait_for_terminal`` confirms the command completed
— never in reaction to the ``CommandCompleted`` event, which is published
*before* the completing transaction commits (see ``CommandGateway._run``),
making a fresh-session event subscriber racy against an uncommitted write.
Adding a future artifact-producing command type means adding a branch here,
not teaching either caller — least of all the Workflow engine's own
step-dispatch logic, which must stay command-type-agnostic — anything new.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.database import Database
from app.domains.snapshots.models import Snapshot
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.service import WorkflowService

_SNAPSHOT_COMMAND_TYPE = "camera.snapshot"


async def record_snapshot_from_command(
    database: Database,
    *,
    command_type: str,
    device_id: UUID,
    command_id: UUID,
    result: dict[str, Any],
    workflow_run_id: UUID | None = None,
) -> Snapshot | None:
    """Persist a completed command's artifact, or no-op if its type doesn't produce one."""
    if command_type != _SNAPSHOT_COMMAND_TYPE:
        return None
    async with database.session_factory() as session:
        workflow_id: UUID | None = None
        if workflow_run_id is not None:
            run = await WorkflowService(WorkflowRepository(session)).get_run(workflow_run_id)
            workflow_id = run.workflow_id
        service = SnapshotService(SnapshotRepository(session))
        snapshot = await service.record_snapshot(
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
        await session.commit()
        return snapshot


def _parse_timestamp(value: object) -> datetime | None:
    """Best-effort parse of a device-reported ISO 8601 timestamp string."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
