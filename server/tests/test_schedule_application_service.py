"""Application-service tests for ScheduleApplicationService.

Mirrors ``test_workflow_service.py``'s "fake agent via a second, independent
session" pattern for simulating a device completing a command, and
``test_application_services.py``'s ``FakeBotoClient``/``S3Client`` pattern
for the cascade-delete Snapshot leg.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.application.dto.device_dto import DeviceDTO
from app.application.events.bus import EventBus
from app.application.exceptions import ScheduleNotFoundError, ScheduleWorkflowNotFoundError
from app.application.services.device_service import DeviceApplicationService
from app.application.services.schedule_run_registry import ScheduleRunRegistry
from app.application.services.schedule_service import ScheduleApplicationService
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
from app.domains.saved_media.models import SavedMedia
from app.domains.saved_media.repository import SavedMediaRepository
from app.domains.saved_media.service import SavedMediaService
from app.domains.schedules.models import Schedule, ScheduleRunStatus, ScheduleType
from app.domains.schedules.schemas import ScheduleCreate
from app.domains.workflows.models import WorkflowRun, WorkflowStepType
from app.domains.workflows.schemas import WorkflowCreate, WorkflowStepCreate

SNAPSHOT_RESULT = {
    "bucket": "samslab-snapshots",
    "filename": "snapshot-schedule-test.jpg",
    "original_object_key": "originals/snapshot-schedule-test.jpg",
    "thumbnail_object_key": "thumbnails/snapshot-schedule-test.jpg",
    "etag": '"abc123"',
    "sha256": "a" * 64,
    "width": 1920,
    "height": 1080,
    "size": 204800,
    "captured_at": "2026-01-01T00:00:00+00:00",
}


class _FakeS3BotoClient:
    def __init__(self) -> None:
        self.delete_calls: list[dict[str, object]] = []

    def generate_presigned_url(
        self, client_method: str, *, Params: dict[str, object], ExpiresIn: int
    ) -> str:
        return "https://s3.example/signed"

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        self.delete_calls.append(kwargs)
        return {}


class _FakeScheduler:
    """A hand-rolled double for ``SchedulerPort`` — no real APScheduler involved."""

    def __init__(self) -> None:
        self.registered: list[Schedule] = []
        self.unregistered: list[UUID] = []
        self._next_run_times: dict[UUID, datetime] = {}

    def register(self, schedule: Schedule) -> None:
        self.registered.append(schedule)
        self._next_run_times[schedule.id] = datetime.now(UTC) + timedelta(minutes=5)

    def unregister(self, schedule_id: UUID) -> None:
        self.unregistered.append(schedule_id)
        self._next_run_times.pop(schedule_id, None)

    def next_run_time(self, schedule_id: UUID) -> datetime | None:
        return self._next_run_times.get(schedule_id)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'schedule_app_service.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def device(database: Database, event_bus: EventBus) -> DeviceDTO:
    async with database.session_factory() as session:
        service = DeviceApplicationService(DeviceService(DeviceRepository(session)), event_bus)
        registered = await service.register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "schedule-test-pi",
                    "hostname": "schedule-test-pi.local",
                    "display_name": "Schedule Test Pi",
                }
            )
        )
        await session.commit()
        return registered


@pytest.fixture
def workflow_app_service(database: Database, event_bus: EventBus) -> WorkflowApplicationService:
    return WorkflowApplicationService(
        database=database,
        event_bus=event_bus,
        run_registry=WorkflowRunRegistry(),
        command_timeout_seconds=2.0,
        command_poll_interval_seconds=0.02,
    )


@pytest.fixture
def fake_scheduler() -> _FakeScheduler:
    return _FakeScheduler()


@pytest.fixture
def schedule_app_service(
    database: Database,
    workflow_app_service: WorkflowApplicationService,
    fake_scheduler: _FakeScheduler,
) -> ScheduleApplicationService:
    return ScheduleApplicationService(
        database=database,
        workflow_app_service=workflow_app_service,
        scheduler=fake_scheduler,
        run_registry=ScheduleRunRegistry(),
        run_outcome_poll_interval_seconds=0.02,
        run_outcome_timeout_seconds=5.0,
    )


def _cron_request(workflow_id: UUID, **overrides: Any) -> ScheduleCreate:
    defaults: dict[str, object] = {
        "workflow_id": workflow_id,
        "name": "Test schedule",
        "enabled": True,
        "schedule_type": ScheduleType.CRON,
        "cron_expression": "*/5 * * * *",
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return ScheduleCreate(**defaults)


async def _complete_pending_commands(
    database: Database,
    device_id: UUID,
    command_type: str,
    *,
    result: dict[str, object] | None = None,
    error_message: str | None = None,
) -> None:
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
            await session.commit()
            if matches:
                return
    raise AssertionError(f"no pending {command_type} command appeared in time")


async def _wait_for_last_status(
    schedule_app_service: ScheduleApplicationService,
    schedule_id: UUID,
    status: ScheduleRunStatus,
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dto = await schedule_app_service.get_schedule(schedule_id)
        if dto.last_status == status:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"schedule {schedule_id} never reached last_status={status}")


async def _create_snapshot_workflow(
    workflow_app_service: WorkflowApplicationService, *, name: str = "Scheduled snapshot workflow"
) -> UUID:
    created = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name=name,
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot")],
        )
    )
    return created.id


async def test_create_schedule_raises_when_workflow_does_not_exist(
    schedule_app_service: ScheduleApplicationService,
) -> None:
    with pytest.raises(ScheduleWorkflowNotFoundError):
        await schedule_app_service.create_schedule(_cron_request(uuid4()))


async def test_create_schedule_registers_live_job_when_enabled(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    fake_scheduler: _FakeScheduler,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    dto = await schedule_app_service.create_schedule(_cron_request(workflow_id))
    assert len(fake_scheduler.registered) == 1
    assert fake_scheduler.registered[0].id == dto.id
    assert dto.next_run_at is not None
    assert dto.workflow_name == "Scheduled snapshot workflow"


async def test_create_schedule_does_not_register_when_disabled(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    fake_scheduler: _FakeScheduler,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    dto = await schedule_app_service.create_schedule(_cron_request(workflow_id, enabled=False))
    assert fake_scheduler.registered == []
    assert dto.next_run_at is None


async def test_enable_and_disable_toggle_live_registration(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    fake_scheduler: _FakeScheduler,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    disabled = await schedule_app_service.disable_schedule(created.id)
    assert disabled.enabled is False
    assert disabled.next_run_at is None
    assert created.id in fake_scheduler.unregistered

    enabled = await schedule_app_service.enable_schedule(created.id)
    assert enabled.enabled is True
    assert enabled.next_run_at is not None
    assert len(fake_scheduler.registered) == 2  # once on create, once on re-enable


async def test_run_now_executes_the_workflow_without_bumping_schedule_bookkeeping(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    device: DeviceDTO,
    database: Database,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    detail, _ = await asyncio.gather(
        schedule_app_service.run_now(created.id),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    assert detail.latest_run is not None
    refreshed = await schedule_app_service.get_schedule(created.id)
    assert refreshed.run_count == 0
    assert refreshed.last_run_at is None
    assert refreshed.last_status is None
    executions = await schedule_app_service.list_executions(offset=0, limit=10)
    assert executions.total == 0


async def test_execute_schedule_success_bookkeeping_and_outcome_follow_up(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    device: DeviceDTO,
    database: Database,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    await asyncio.gather(
        schedule_app_service.execute_schedule(created.id),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    fresh = await schedule_app_service.get_schedule(created.id)
    assert fresh.run_count == 1
    assert fresh.last_run_at is not None

    executions = await schedule_app_service.list_executions(offset=0, limit=10)
    assert executions.total == 1
    assert executions.items[0].schedule_name == "Test schedule"
    assert executions.items[0].workflow_run_id is not None

    await _wait_for_last_status(schedule_app_service, created.id, ScheduleRunStatus.COMPLETED)
    executions_after = await schedule_app_service.list_executions(offset=0, limit=10)
    assert executions_after.items[0].status == ScheduleRunStatus.COMPLETED


async def test_execute_schedule_records_failure_when_workflow_is_disabled(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
) -> None:
    created_workflow = await workflow_app_service.create_workflow(
        WorkflowCreate(
            name="Disabled workflow",
            enabled=False,
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
        )
    )
    schedule = await schedule_app_service.create_schedule(_cron_request(created_workflow.id))

    await schedule_app_service.execute_schedule(schedule.id)

    fresh = await schedule_app_service.get_schedule(schedule.id)
    assert fresh.run_count == 1
    assert fresh.last_status == ScheduleRunStatus.FAILED
    executions = await schedule_app_service.list_executions(offset=0, limit=10)
    assert executions.items[0].status == ScheduleRunStatus.FAILED
    assert executions.items[0].error_message is not None


async def test_execute_schedule_auto_disables_a_one_time_schedule_after_firing(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    device: DeviceDTO,
    database: Database,
    fake_scheduler: _FakeScheduler,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(
        _cron_request(
            workflow_id,
            schedule_type=ScheduleType.ONE_TIME,
            cron_expression=None,
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )

    await asyncio.gather(
        schedule_app_service.execute_schedule(created.id),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )

    fresh = await schedule_app_service.get_schedule(created.id)
    assert fresh.enabled is False
    assert created.id in fake_scheduler.unregistered


async def test_delete_schedule_without_artifacts_keeps_generated_snapshot_and_run(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    device: DeviceDTO,
    database: Database,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    await asyncio.gather(
        schedule_app_service.execute_schedule(created.id),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )
    await _wait_for_last_status(schedule_app_service, created.id, ScheduleRunStatus.COMPLETED)
    executions = await schedule_app_service.list_executions(offset=0, limit=10)
    run_id = executions.items[0].workflow_run_id
    assert run_id is not None

    await schedule_app_service.delete_schedule(created.id)

    with pytest.raises(ScheduleNotFoundError):
        await schedule_app_service.get_schedule(created.id)

    async with database.session_factory() as session:
        media_rows = list((await session.execute(select(SavedMedia))).scalars())
        runs = list((await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalars())
    assert len(media_rows) == 1
    assert len(runs) == 1


async def test_delete_schedule_with_artifacts_removes_generated_snapshot_command_and_run(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    device: DeviceDTO,
    database: Database,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    await asyncio.gather(
        schedule_app_service.execute_schedule(created.id),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )
    await _wait_for_last_status(schedule_app_service, created.id, ScheduleRunStatus.COMPLETED)
    executions = await schedule_app_service.list_executions(offset=0, limit=10)
    run_id = executions.items[0].workflow_run_id
    assert run_id is not None

    await schedule_app_service.delete_schedule(created.id, delete_artifacts=True)

    async with database.session_factory() as session:
        media_rows, _ = await SavedMediaService(SavedMediaRepository(session)).list_media(
            device_id=None, media_type=None, captured_after=None, offset=0, limit=10
        )
        runs = list((await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalars())
        commands = list(
            (
                await session.execute(
                    select(Command).where(Command.correlation_id == run_id, Command.deleted_at.is_(None))
                )
            ).scalars()
        )
    assert media_rows == []
    assert runs == []
    assert commands == []

    # The workflow *definition* itself must remain completely untouched.
    workflow_detail = await workflow_app_service.get_workflow(workflow_id)
    assert workflow_detail.id == workflow_id


async def test_delete_schedule_with_artifacts_skips_a_non_terminal_command_without_blocking(
    schedule_app_service: ScheduleApplicationService,
    workflow_app_service: WorkflowApplicationService,
    device: DeviceDTO,
    database: Database,
) -> None:
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    # Fire the schedule but never complete the command it creates — it stays PENDING.
    await schedule_app_service.execute_schedule(created.id)
    executions = await schedule_app_service.list_executions(offset=0, limit=10)
    run_id = executions.items[0].workflow_run_id
    assert run_id is not None

    await schedule_app_service.delete_schedule(created.id, delete_artifacts=True)

    async with database.session_factory() as session:
        commands = list(
            (
                await session.execute(
                    select(Command).where(Command.correlation_id == run_id, Command.deleted_at.is_(None))
                )
            ).scalars()
        )
        runs = list((await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalars())
    # The non-terminal command survives (best-effort skip)...
    assert len(commands) == 1
    # ...but the WorkflowRun/StepRun rows are still removed regardless.
    assert runs == []


async def test_cascade_delete_attempts_s3_delete_via_existing_saved_media_service(
    workflow_app_service: WorkflowApplicationService,
    database: Database,
    device: DeviceDTO,
) -> None:
    fake_boto = _FakeS3BotoClient()
    schedule_app_service = ScheduleApplicationService(
        database=database,
        workflow_app_service=workflow_app_service,
        scheduler=_FakeScheduler(),
        run_registry=ScheduleRunRegistry(),
        run_outcome_poll_interval_seconds=0.02,
        run_outcome_timeout_seconds=5.0,
        s3_client=S3Client(client=fake_boto, bucket="test-bucket"),
    )
    workflow_id = await _create_snapshot_workflow(workflow_app_service)
    created = await schedule_app_service.create_schedule(_cron_request(workflow_id))

    await asyncio.gather(
        schedule_app_service.execute_schedule(created.id),
        _complete_pending_commands(database, device.id, "camera.snapshot", result=SNAPSHOT_RESULT),
    )
    await _wait_for_last_status(schedule_app_service, created.id, ScheduleRunStatus.COMPLETED)

    await schedule_app_service.delete_schedule(created.id, delete_artifacts=True)
    assert len(fake_boto.delete_calls) == 2  # original + thumbnail
