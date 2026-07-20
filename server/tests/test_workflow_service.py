"""Application-service tests for Workflow execution (`WorkflowApplicationService.run_workflow`).

Mirrors ``test_camera.py``'s "fake agent via a second, independent session"
pattern for simulating a device completing a command — see that module's
docstring for why this matches production more faithfully than mocking the
dispatcher directly. Since ``run_workflow`` detaches its execution into a
background ``asyncio.Task`` (unlike ``CameraApplicationService.start_stream``,
which blocks the caller), tests additionally poll ``get_workflow`` for the
run to reach a terminal state rather than just awaiting the call directly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.application.dto.device_dto import DeviceDTO
from app.application.dto.workflow_dto import WorkflowDetailDTO
from app.application.events.bus import EventBus
from app.application.exceptions import (
    WorkflowDisabledError,
    WorkflowNotFoundError,
)
from app.application.services.device_service import DeviceApplicationService
from app.application.services.workflow_run_registry import WorkflowRunRegistry
from app.application.services.workflow_service import WorkflowApplicationService
from app.core.database import Database
from app.core.s3_client import S3Client
from app.domains.commands.models import Command
from app.domains.commands.repository import CommandRepository
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService
from app.domains.saved_media.models import MediaType
from app.domains.saved_media.repository import SavedMediaRepository
from app.domains.saved_media.service import SavedMediaService
from app.domains.workflows.models import (
    WorkflowGroupMode,
    WorkflowRunStatus,
    WorkflowStepRunStatus,
    WorkflowStepType,
)
from app.domains.workflows.schemas import WorkflowCreate, WorkflowStepCreate, WorkflowUpdate
from app.notifications.events import WorkflowCompleted, WorkflowFailed

# A realistic camera.snapshot command result (mirrors test_camera.py's own
# SNAPSHOT_RESULT) — record_snapshot_from_command needs these exact keys to
# persist a Snapshot row; an empty {} result is only ever realistic for
# command types that don't produce an artifact (e.g. camera.stream.start).
SNAPSHOT_RESULT = {
    "bucket": "samslab-snapshots",
    "filename": "snapshot-20260101T000000Z.jpg",
    "original_object_key": "originals/snapshot-20260101T000000Z.jpg",
    "thumbnail_object_key": "thumbnails/snapshot-20260101T000000Z.jpg",
    "etag": '"abc123"',
    "sha256": "a" * 64,
    "width": 1920,
    "height": 1080,
    "size": 204800,
    "captured_at": "2026-01-01T00:00:00+00:00",
}


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'workflow_service.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
def event_bus() -> EventBus:
    """Provide a fresh, unshared event bus so tests can assert on exactly what fired."""
    return EventBus()


@pytest.fixture
def workflow_app_service(database: Database, event_bus: EventBus) -> WorkflowApplicationService:
    """Provide a workflow application service with fast timeouts suited to tests."""
    return WorkflowApplicationService(
        database=database,
        event_bus=event_bus,
        run_registry=WorkflowRunRegistry(),
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )


@pytest.fixture
async def device(database: Database, event_bus: EventBus) -> DeviceDTO:
    """Register and commit one enabled device that Command Task steps can target."""
    async with database.session_factory() as session:
        service = DeviceApplicationService(DeviceService(DeviceRepository(session)), event_bus)
        registered = await service.register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "garden-pi",
                    "hostname": "garden-pi.local",
                    "display_name": "Garden Pi",
                }
            )
        )
        await session.commit()
        return registered


async def _complete_pending_commands(
    database: Database,
    device_id: UUID,
    command_type: str,
    *,
    count: int = 1,
    error_message: str | None = None,
    result: dict[str, object] | None = None,
) -> None:
    """Simulate the dispatcher/agent finishing every pending command of one type.

    ``result`` matters for ``camera.snapshot`` specifically: since
    ``record_snapshot_from_command`` now persists a Snapshot from it, an
    empty ``{}`` (this function's default, realistic for a command type
    like ``camera.stream.start`` that produces no artifact) would raise a
    ``KeyError`` — pass ``SNAPSHOT_RESULT`` for any test completing a real
    ``camera.snapshot`` command successfully.
    """
    completed = 0
    for _ in range(300):
        await asyncio.sleep(0.01)
        async with database.session_factory() as session:
            command_service = CommandService(CommandRepository(session))
            pending = await command_service.find_pending(device_id=device_id, limit=20)
            matches = [c for c in pending if c.command_type == command_type]
            for match in matches:
                await command_service.mark_dispatched(match.id)
                if error_message is not None:
                    await command_service.fail_command(match.id, error_message=error_message)
                else:
                    await command_service.mark_running(match.id)
                    await command_service.complete_command(match.id, result=result or {})
                completed += 1
            await session.commit()
        if completed >= count:
            return
    raise AssertionError(
        f"only {completed}/{count} pending {command_type} commands appeared in time"
    )


async def _wait_for_run_terminal(
    app_service: WorkflowApplicationService, workflow_id: UUID, *, timeout: float = 5.0
) -> WorkflowDetailDTO:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = await app_service.get_workflow(workflow_id)
        if detail.latest_run is not None and detail.latest_run.status != WorkflowRunStatus.RUNNING:
            return detail
        await asyncio.sleep(0.02)
    raise AssertionError("workflow run did not reach a terminal state in time")


async def test_run_workflow_executes_command_then_sleep_serially(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Snapshot then wait",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                ),
                WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1),
            ],
        )
    )

    started = await workflow_app_service.run_workflow(created.id)
    assert started.latest_run is not None
    assert started.latest_run.status == WorkflowRunStatus.RUNNING

    detail, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.COMPLETED
    statuses = [step.status for step in detail.latest_run.step_runs]
    assert statuses == [WorkflowStepRunStatus.COMPLETED, WorkflowStepRunStatus.COMPLETED]
    assert detail.run_count == 1
    assert detail.last_run_status == WorkflowRunStatus.COMPLETED


async def test_run_workflow_camera_snapshot_step_persists_a_linked_snapshot(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    """Regression test: a workflow-driven camera.snapshot must appear in the Gallery.

    Before ``record_snapshot_from_command`` existed, ``_execute_command_step``
    created/awaited the command via the generic ``CommandApplicationService``
    only — the agent captured and uploaded fine, but the server never
    persisted a ``Snapshot`` row, since that only ever happened inside
    ``CameraApplicationService.capture_snapshot``, a code path the workflow
    engine never goes through.
    """
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Nightly snapshot",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )

    started = await workflow_app_service.run_workflow(created.id)
    run_id = started.latest_run.id if started.latest_run else None
    assert run_id is not None

    detail, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )
    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.COMPLETED

    async with database.session_factory() as session:
        media_rows = await SavedMediaService(SavedMediaRepository(session)).list_media(
            device_id=None, media_type=None, captured_after=None, offset=0, limit=10
        )
    items, total = media_rows
    assert total == 1
    media = items[0]
    assert media.filename == SNAPSHOT_RESULT["filename"]
    assert media.workflow_id == created.id
    assert media.workflow_run_id == run_id


async def test_run_workflow_parallel_group_waits_for_all_children(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Two cameras",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.GROUP,
                    group_mode=WorkflowGroupMode.PARALLEL,
                    children=[
                        WorkflowStepCreate(
                            step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                        ),
                        WorkflowStepCreate(
                            step_type=WorkflowStepType.COMMAND, command_type="camera.stream.start"
                        ),
                    ],
                )
            ],
        )
    )

    await workflow_app_service.run_workflow(created.id)

    detail, _, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
        _complete_pending_commands(database, device.id, "camera.stream.start"),
    )

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.COMPLETED
    group_run = detail.latest_run.step_runs[0]
    assert group_run.status == WorkflowStepRunStatus.COMPLETED
    assert len(group_run.children) == 2
    assert all(child.status == WorkflowStepRunStatus.COMPLETED for child in group_run.children)


async def test_run_workflow_fails_the_run_when_a_command_fails(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Doomed",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                ),
                WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=5),
            ],
        )
    )

    await workflow_app_service.run_workflow(created.id)

    detail, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(
            database, device.id, "camera.snapshot", error_message="camera not detected"
        ),
    )

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.FAILED
    assert detail.latest_run.step_runs[0].status == WorkflowStepRunStatus.FAILED
    # The sleep step never started because the run aborts on first failure.
    assert detail.latest_run.step_runs[1].status == WorkflowStepRunStatus.PENDING


async def test_run_workflow_publishes_a_workflow_completed_notification_event(
    workflow_app_service: WorkflowApplicationService,
    database: Database,
    device: DeviceDTO,
    event_bus: EventBus,
) -> None:
    """The Workflow Engine's one integration point with the Notification Framework.

    Subscribes a plain probe to the same event bus the application service
    was built with — proving ``_finish_run`` actually publishes
    ``WorkflowCompleted`` with the right data, without needing a real
    Telegram provider or NotificationService at all.
    """
    published: list[WorkflowCompleted] = []
    event_bus.subscribe(WorkflowCompleted, published.append)

    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Morning Garden",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )
    started = await workflow_app_service.run_workflow(created.id)
    run_id = started.latest_run.id if started.latest_run else None
    assert run_id is not None

    await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    assert len(published) == 1
    event = published[0]
    assert event.workflow_id == created.id
    assert event.workflow_name == "Morning Garden"
    assert event.execution_id == run_id
    assert event.status == "COMPLETED"
    assert event.trigger_source == "Manual"
    assert event.duration_seconds >= 0.0
    assert event.completed_at >= event.started_at
    assert event.thumbnail_object_key == SNAPSHOT_RESULT["thumbnail_object_key"]


async def test_run_workflow_completed_event_has_no_thumbnail_when_no_media_was_generated(
    workflow_app_service: WorkflowApplicationService,
    database: Database,
    event_bus: EventBus,
) -> None:
    published: list[WorkflowCompleted] = []
    event_bus.subscribe(WorkflowCompleted, published.append)

    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="No Media Here",
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
        )
    )
    await workflow_app_service.run_workflow(created.id)
    await _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0)

    assert len(published) == 1
    assert published[0].thumbnail_object_key is None


async def test_run_workflow_completed_event_prefers_the_first_snapshot_when_two_steps_produce_media(
    workflow_app_service: WorkflowApplicationService,
    database: Database,
    device: DeviceDTO,
    event_bus: EventBus,
) -> None:
    """ "first one if multiple" — the earlier-completed step's thumbnail wins."""
    published: list[WorkflowCompleted] = []
    event_bus.subscribe(WorkflowCompleted, published.append)
    second_snapshot_result = {
        **SNAPSHOT_RESULT,
        "filename": "snapshot-2.jpg",
        "original_object_key": "originals/snapshot-2.jpg",
        "thumbnail_object_key": "thumbnails/snapshot-2.jpg",
        "sha256": "b" * 64,
    }

    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Two Snapshots",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                ),
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                ),
            ],
        )
    )
    await workflow_app_service.run_workflow(created.id)

    # The two camera.snapshot steps run serially, so completing all pending
    # commands of that type one poll cycle at a time (rather than both at
    # once) is what makes the *first* step's result the one persisted first.
    await _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT)
    await _complete_pending_commands(
        database, device.id, "camera.snapshot", result=second_snapshot_result
    )
    await _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0)

    assert len(published) == 1
    assert published[0].thumbnail_object_key == SNAPSHOT_RESULT["thumbnail_object_key"]


async def test_resolve_thumbnail_object_key_prefers_a_snapshot_over_a_video(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    """Video thumbnail generation isn't implemented yet (SavedMedia.thumbnail_object_key
    is always None for MediaType.VIDEO in the real pipeline — see that model's
    docstring), so this exercises the preference rule directly against
    manually seeded rows rather than through a real camera.record.stop
    result, the only way to prove "snapshot beats video" today.
    """
    run_id = uuid4()
    async with database.session_factory() as session:
        media_service = SavedMediaService(SavedMediaRepository(session))
        video_command = await CommandRepository(session).create(
            Command(device_id=device.id, command_type="camera.record.stop", payload={})
        )
        image_command = await CommandRepository(session).create(
            Command(device_id=device.id, command_type="camera.snapshot", payload={})
        )
        now = datetime.now(UTC)
        # Created *after* the image row, to prove type-preference beats
        # simple creation-order rather than coincidentally matching it.
        await media_service.record_media(
            media_type=MediaType.VIDEO,
            device_id=device.id,
            command_id=video_command.id,
            filename="recording.mp4",
            bucket="samslab-media",
            original_object_key="originals/recording.mp4",
            thumbnail_object_key="thumbnails/recording.jpg",
            etag=None,
            sha256="c" * 64,
            width=1920,
            height=1080,
            size=1_000_000,
            captured_at=now,
            workflow_run_id=run_id,
        )
        await media_service.record_media(
            media_type=MediaType.IMAGE,
            device_id=device.id,
            command_id=image_command.id,
            filename="snapshot.jpg",
            bucket="samslab-media",
            original_object_key="originals/snapshot.jpg",
            thumbnail_object_key="thumbnails/snapshot.jpg",
            etag=None,
            sha256="d" * 64,
            width=1920,
            height=1080,
            size=204800,
            captured_at=now,
            workflow_run_id=run_id,
        )
        await session.commit()

        thumbnail_object_key = await workflow_app_service._resolve_thumbnail_object_key(  # noqa: SLF001
            session, run_id
        )

    assert thumbnail_object_key == "thumbnails/snapshot.jpg"


async def test_run_workflow_publishes_a_workflow_failed_notification_event(
    workflow_app_service: WorkflowApplicationService,
    database: Database,
    device: DeviceDTO,
    event_bus: EventBus,
) -> None:
    published: list[WorkflowFailed] = []
    event_bus.subscribe(WorkflowFailed, published.append)

    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Doomed Garden",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )
    # Exercises trigger_source end-to-end too — schedule_service.py passes
    # this exact keyword from its own execute_schedule.
    await workflow_app_service.run_workflow(created.id, trigger_source="Schedule")

    await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(
            database, device.id, "camera.snapshot", error_message="camera not detected"
        ),
    )

    assert len(published) == 1
    event = published[0]
    assert event.workflow_name == "Doomed Garden"
    assert event.status == "FAILED"
    assert event.trigger_source == "Schedule"
    # The run-level error is _wait_for_terminal's own wrapper message, not
    # the command's original error text — matches the existing
    # test_run_workflow_fails_the_run_when_a_command_fails, which asserts
    # the same thing indirectly by never checking the run's error_message.
    assert "ended in status FAILED" in event.error_message
    assert event.failed_step == "camera.snapshot"


async def test_run_workflow_completes_even_if_a_notification_subscriber_raises(
    workflow_app_service: WorkflowApplicationService,
    database: Database,
    device: DeviceDTO,
    event_bus: EventBus,
) -> None:
    """The other half of "notification failures must never affect workflow execution".

    ``test_notifications_service.py`` proves ``NotificationService`` itself
    never raises; this proves the second, independent safety net in
    ``WorkflowApplicationService._publish_notification_event`` — a
    completely broken subscriber (not just a broken provider) still can't
    stop the run from reaching its terminal, persisted status.
    """

    def _explode(_event: WorkflowCompleted) -> None:
        raise RuntimeError("a notification subscriber blew up")

    event_bus.subscribe(WorkflowCompleted, _explode)

    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Resilient Garden",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )
    await workflow_app_service.run_workflow(created.id)

    detail, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.COMPLETED


async def test_run_workflow_raises_when_disabled(
    workflow_app_service: WorkflowApplicationService, device: DeviceDTO
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Disabled",
            enabled=False,
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
        )
    )

    with pytest.raises(WorkflowDisabledError):
        await workflow_app_service.run_workflow(created.id)


async def test_get_workflow_raises_not_found_for_missing_id(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    with pytest.raises(WorkflowNotFoundError):
        await workflow_app_service.get_workflow(uuid4())


# --- A. Parallel-group cancellation semantics -------------------------------


async def test_parallel_group_cancels_the_sibling_of_a_failed_command(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    """One failing branch of a PARALLEL group must cancel — not strand RUNNING — its sibling.

    The two children use distinct command_types so `_complete_pending_commands`
    can be told to resolve only one of them (with a failure), leaving the
    other's command PENDING/undispatched long enough for asyncio.gather's
    cancellation to reach it before this test's own timeout.
    """
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Racing cameras",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.GROUP,
                    group_mode=WorkflowGroupMode.PARALLEL,
                    children=[
                        WorkflowStepCreate(
                            step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                        ),
                        WorkflowStepCreate(
                            step_type=WorkflowStepType.COMMAND, command_type="camera.stream.start"
                        ),
                    ],
                )
            ],
        )
    )
    failing_child_id = created.steps[0].children[0].id
    stranded_child_id = created.steps[0].children[1].id

    await workflow_app_service.run_workflow(created.id)

    detail, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(
            database, device.id, "camera.snapshot", error_message="camera not detected"
        ),
    )

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.FAILED
    group_run = detail.latest_run.step_runs[0]
    assert group_run.status == WorkflowStepRunStatus.FAILED

    failed_child = next(c for c in group_run.children if c.workflow_step_id == failing_child_id)
    cancelled_child = next(c for c in group_run.children if c.workflow_step_id == stranded_child_id)

    assert failed_child.status == WorkflowStepRunStatus.FAILED
    assert failed_child.error_message is not None
    assert cancelled_child.status == WorkflowStepRunStatus.CANCELLED


# --- B. Nested (GROUP-within-GROUP) execution -------------------------------


async def test_run_workflow_executes_a_nested_parallel_group_inside_a_serial_group(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    """A top-level SERIAL group containing a nested PARALLEL group of two commands."""
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Nested group",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.GROUP,
                    group_mode=WorkflowGroupMode.SERIAL,
                    children=[
                        WorkflowStepCreate(
                            step_type=WorkflowStepType.GROUP,
                            group_mode=WorkflowGroupMode.PARALLEL,
                            children=[
                                WorkflowStepCreate(
                                    step_type=WorkflowStepType.COMMAND,
                                    command_type="camera.snapshot",
                                ),
                                WorkflowStepCreate(
                                    step_type=WorkflowStepType.COMMAND,
                                    command_type="camera.stream.start",
                                ),
                            ],
                        )
                    ],
                )
            ],
        )
    )

    await workflow_app_service.run_workflow(created.id)

    detail, _, _ = await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
        _complete_pending_commands(database, device.id, "camera.stream.start"),
    )

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.COMPLETED

    outer_group_run = detail.latest_run.step_runs[0]
    assert outer_group_run.status == WorkflowStepRunStatus.COMPLETED
    assert len(outer_group_run.children) == 1

    inner_group_run = outer_group_run.children[0]
    assert inner_group_run.status == WorkflowStepRunStatus.COMPLETED
    assert len(inner_group_run.children) == 2
    assert all(
        child.status == WorkflowStepRunStatus.COMPLETED for child in inner_group_run.children
    )


# --- C. Timeout path ---------------------------------------------------------


async def test_run_workflow_fails_when_a_command_never_completes_within_the_timeout(
    database: Database, event_bus: EventBus, device: DeviceDTO
) -> None:
    """A Command Task whose command is never resolved by the simulated agent times out."""
    fast_timeout_service = WorkflowApplicationService(
        database=database,
        event_bus=event_bus,
        run_registry=WorkflowRunRegistry(),
        command_timeout_seconds=0.1,
        command_poll_interval_seconds=0.02,
    )
    created = await fast_timeout_service.create_workflow(
        WorkflowCreate(
            name="Never answers",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )

    await fast_timeout_service.run_workflow(created.id)

    detail = await _wait_for_run_terminal(fast_timeout_service, created.id, timeout=3.0)

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.FAILED
    step_run = detail.latest_run.step_runs[0]
    assert step_run.status == WorkflowStepRunStatus.FAILED
    assert step_run.error_message is not None
    assert "did not complete within" in step_run.error_message


# --- D. WorkflowDeviceNotFoundError ------------------------------------------


async def test_run_workflow_fails_the_run_when_no_device_is_registered(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    """`_require_primary_device_id` is only ever called from inside the detached task.

    So a missing device does NOT raise synchronously out of `run_workflow` —
    the run starts RUNNING as usual and only reaches FAILED once the
    background task's Command Task step actually tries (and fails) to
    resolve a target device.
    """
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Nobody home",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )

    started = await workflow_app_service.run_workflow(created.id)
    assert started.latest_run is not None
    assert started.latest_run.status == WorkflowRunStatus.RUNNING

    detail = await _wait_for_run_terminal(workflow_app_service, created.id, timeout=3.0)

    assert detail.latest_run is not None
    assert detail.latest_run.status == WorkflowRunStatus.FAILED
    step_run = detail.latest_run.step_runs[0]
    assert step_run.status == WorkflowStepRunStatus.FAILED
    assert step_run.error_message is not None
    assert "No registered device" in step_run.error_message


# --- E. CRUD via the application service -------------------------------------


def test_workflow_step_create_rejects_a_parallel_group_with_only_one_child() -> None:
    """Schema-level validation, before any of this ever reaches the service."""
    with pytest.raises(ValidationError):
        WorkflowStepCreate(
            step_type=WorkflowStepType.GROUP,
            group_mode=WorkflowGroupMode.PARALLEL,
            children=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
        )


def test_workflow_step_create_rejects_an_invalid_command_type() -> None:
    """`nothash` has no dot, so it fails the reused Command-domain validator."""
    with pytest.raises(ValidationError):
        WorkflowStepCreate(step_type=WorkflowStepType.COMMAND, command_type="nothash")


def test_workflow_step_create_accepts_an_explicit_null_command_type() -> None:
    """The field validator's None-passthrough branch, only reached when explicitly provided."""
    step = WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, command_type=None, sleep_seconds=5)
    assert step.command_type is None


def test_workflow_step_create_rejects_a_command_step_without_a_command_type() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepCreate(step_type=WorkflowStepType.COMMAND)


def test_workflow_step_create_rejects_a_sleep_step_without_sleep_seconds() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepCreate(step_type=WorkflowStepType.SLEEP)


def test_workflow_step_create_rejects_a_group_step_without_a_group_mode() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepCreate(
            step_type=WorkflowStepType.GROUP,
            children=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
        )


def test_workflow_step_create_rejects_a_group_step_with_no_children() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepCreate(step_type=WorkflowStepType.GROUP, group_mode=WorkflowGroupMode.SERIAL)


def test_workflow_create_rejects_an_explicitly_empty_step_list() -> None:
    with pytest.raises(ValidationError):
        WorkflowCreate(name="Empty", steps=[])


async def test_update_workflow_raises_not_found_for_missing_id(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    with pytest.raises(WorkflowNotFoundError):
        await workflow_app_service.update_workflow(
            uuid4(),
            WorkflowUpdate(
                name="Ghost",
                steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
            ),
        )


async def test_delete_workflow_raises_not_found_for_missing_id(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    with pytest.raises(WorkflowNotFoundError):
        await workflow_app_service.delete_workflow(uuid4())


async def test_update_workflow_replaces_the_step_tree_via_application_service(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Original",
            steps=[
                WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1),
                WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=2),
            ],
        )
    )
    assert len(created.steps) == 2

    updated = await workflow_app_service.update_workflow(
        created.id,
        WorkflowUpdate(
            name="Replaced",
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=99)],
        ),
    )

    assert updated.name == "Replaced"
    assert len(updated.steps) == 1
    assert updated.steps[0].sleep_seconds == 99

    refetched = await workflow_app_service.get_workflow(created.id)
    assert len(refetched.steps) == 1
    assert refetched.steps[0].sleep_seconds == 99


class _FakeS3BotoClient:
    """Hand-rolled double for the boto3 S3 client slice app.core.s3_client.S3Client calls."""

    def __init__(self) -> None:
        self.delete_calls: list[dict[str, object]] = []

    def generate_presigned_url(
        self, client_method: str, *, Params: dict[str, object], ExpiresIn: int
    ) -> str:
        return "https://s3.example/signed"

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        self.delete_calls.append(kwargs)
        return {}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError("not exercised by these tests")


async def test_delete_workflow_with_delete_artifacts_removes_generated_snapshots(
    database: Database, event_bus: EventBus, device: DeviceDTO
) -> None:
    fake_boto = _FakeS3BotoClient()
    service = WorkflowApplicationService(
        database=database,
        event_bus=event_bus,
        run_registry=WorkflowRunRegistry(),
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
        s3_client=S3Client(client=fake_boto, bucket="test-bucket"),
    )
    created = await service.create_workflow(
        WorkflowCreate(
            name="Snapshot maker",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )
    await service.run_workflow(created.id)
    await asyncio.gather(
        _wait_for_run_terminal(service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )
    async with database.session_factory() as session:
        _, total_before = await SavedMediaService(SavedMediaRepository(session)).list_media(
            device_id=None, media_type=None, captured_after=None, offset=0, limit=10
        )
    assert total_before == 1

    await service.delete_workflow(created.id, delete_artifacts=True)

    async with database.session_factory() as session:
        _, total_after = await SavedMediaService(SavedMediaRepository(session)).list_media(
            device_id=None, media_type=None, captured_after=None, offset=0, limit=10
        )
    assert total_after == 0
    assert len(fake_boto.delete_calls) == 2  # original + thumbnail objects


async def test_delete_workflow_without_delete_artifacts_keeps_generated_snapshots(
    workflow_app_service: WorkflowApplicationService, database: Database, device: DeviceDTO
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Snapshot maker",
            steps=[
                WorkflowStepCreate(
                    step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"
                )
            ],
        )
    )
    await workflow_app_service.run_workflow(created.id)
    await asyncio.gather(
        _wait_for_run_terminal(workflow_app_service, created.id, timeout=6.0),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    await workflow_app_service.delete_workflow(created.id)  # delete_artifacts defaults False

    async with database.session_factory() as session:
        _, total = await SavedMediaService(SavedMediaRepository(session)).list_media(
            device_id=None, media_type=None, captured_after=None, offset=0, limit=10
        )
    assert total == 1


async def test_delete_workflow_then_get_raises_not_found(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Throwaway",
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
        )
    )

    await workflow_app_service.delete_workflow(created.id)

    with pytest.raises(WorkflowNotFoundError):
        await workflow_app_service.get_workflow(created.id)


async def test_list_workflows_paginates_via_application_service(
    workflow_app_service: WorkflowApplicationService,
) -> None:
    for index in range(3):
        await workflow_app_service.create_workflow(
            WorkflowCreate(
                name=f"Workflow {index}",
                steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
            )
        )

    page = await workflow_app_service.list_workflows(offset=0, limit=2)

    assert page.total == 3
    assert len(page.items) == 2
    assert page.offset == 0
    assert page.limit == 2
