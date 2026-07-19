"""Repository and service tests for the Schedules domain."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.database import Database
from app.domains.schedules.exceptions import ScheduleNotFound
from app.domains.schedules.models import ScheduleRunStatus, ScheduleType
from app.domains.schedules.repository import ScheduleRepository
from app.domains.schedules.schemas import ScheduleCreate, ScheduleUpdate
from app.domains.schedules.service import ScheduleService
from app.domains.workflows.models import WorkflowStepType
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowCreate, WorkflowStepCreate
from app.domains.workflows.service import WorkflowService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'schedules.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def service(database: Database) -> AsyncIterator[ScheduleService]:
    """Provide a transaction-scoped service for repository/service tests."""
    async with database.session_factory() as session:
        yield ScheduleService(ScheduleRepository(session))
        try:
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.fixture
async def workflow_id(database: Database) -> UUID:
    """Persist one real workflow a schedule can reference."""
    async with database.session_factory() as session:
        workflow_service = WorkflowService(WorkflowRepository(session))
        workflow = await workflow_service.register_workflow(
            WorkflowCreate(
                name="Nightly patrol",
                steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
            )
        )
        await session.commit()
        return workflow.id


def _cron_request(**overrides: object) -> ScheduleCreate:
    defaults: dict[str, object] = {
        "workflow_id": uuid4(),
        "name": "Every five minutes",
        "description": "Runs often",
        "enabled": True,
        "schedule_type": ScheduleType.CRON,
        "cron_expression": "*/5 * * * *",
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return ScheduleCreate(**defaults)


def _one_time_request(**overrides: object) -> ScheduleCreate:
    defaults: dict[str, object] = {
        "workflow_id": uuid4(),
        "name": "One-off run",
        "enabled": True,
        "schedule_type": ScheduleType.ONE_TIME,
        "run_at": datetime.now(UTC) + timedelta(hours=1),
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return ScheduleCreate(**defaults)


async def test_register_schedule_persists_a_cron_schedule(
    service: ScheduleService, workflow_id: UUID
) -> None:
    schedule = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    assert schedule.id is not None
    assert schedule.schedule_type is ScheduleType.CRON
    assert schedule.cron_expression == "*/5 * * * *"
    assert schedule.enabled is True
    assert schedule.run_count == 0


async def test_register_schedule_persists_a_one_time_schedule(
    service: ScheduleService, workflow_id: UUID
) -> None:
    schedule = await service.register_schedule(_one_time_request(workflow_id=workflow_id))
    assert schedule.schedule_type is ScheduleType.ONE_TIME
    assert schedule.run_at is not None


async def test_get_schedule_raises_not_found_for_missing_id(service: ScheduleService) -> None:
    with pytest.raises(ScheduleNotFound):
        await service.get_schedule(uuid4())


async def test_update_schedule_replaces_fields(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    updated = await service.update_schedule(
        created.id,
        ScheduleUpdate(
            workflow_id=workflow_id,
            name="Renamed",
            schedule_type=ScheduleType.CRON,
            cron_expression="0 0 * * *",
            timezone="UTC",
        ),
    )
    assert updated.name == "Renamed"
    assert updated.cron_expression == "0 0 * * *"


async def test_delete_soft_deletes_and_excludes_from_list_and_get(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    await service.delete(created.id)
    with pytest.raises(ScheduleNotFound):
        await service.get_schedule(created.id)
    schedules, total = await service.list_schedules(
        offset=0, limit=10, enabled=None, workflow_id=None
    )
    assert total == 0
    assert schedules == []


async def test_list_schedules_filters_by_enabled_and_workflow_id(
    service: ScheduleService, workflow_id: UUID
) -> None:
    other_workflow_id = uuid4()
    await service.register_schedule(_cron_request(workflow_id=workflow_id, enabled=True))
    await service.register_schedule(
        _cron_request(workflow_id=other_workflow_id, enabled=False, name="Disabled one")
    )

    enabled_only, enabled_total = await service.list_schedules(
        offset=0, limit=10, enabled=True, workflow_id=None
    )
    assert enabled_total == 1
    assert all(s.enabled for s in enabled_only)

    scoped, scoped_total = await service.list_schedules(
        offset=0, limit=10, enabled=None, workflow_id=other_workflow_id
    )
    assert scoped_total == 1
    assert scoped[0].workflow_id == other_workflow_id


async def test_list_enabled_returns_only_enabled_active_schedules(
    service: ScheduleService, workflow_id: UUID
) -> None:
    enabled = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    disabled = await service.register_schedule(
        _cron_request(workflow_id=workflow_id, enabled=False, name="Off")
    )
    results = await service.list_enabled()
    ids = {s.id for s in results}
    assert enabled.id in ids
    assert disabled.id not in ids


async def test_set_enabled_clears_next_run_at_when_disabling(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    await service.set_next_run_at(created.id, datetime.now(UTC) + timedelta(minutes=5))
    disabled = await service.set_enabled(created.id, enabled=False)
    assert disabled.enabled is False
    assert disabled.next_run_at is None


async def test_record_firing_bumps_bookkeeping_and_creates_execution(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    run_id = uuid4()
    next_run = datetime.now(UTC) + timedelta(minutes=5)
    updated, execution = await service.record_firing(
        created.id,
        workflow_id=workflow_id,
        workflow_run_id=run_id,
        status=ScheduleRunStatus.RUNNING,
        next_run_at=next_run,
    )
    assert updated.run_count == 1
    assert updated.last_status == ScheduleRunStatus.RUNNING
    # SQLite drops tzinfo on round-trip (unlike Postgres) — compare naive.
    assert updated.next_run_at is not None
    assert updated.next_run_at.replace(tzinfo=UTC) == next_run
    assert execution.workflow_run_id == run_id
    assert execution.status == ScheduleRunStatus.RUNNING


async def test_update_execution_status_and_last_status(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    run_id = uuid4()
    _, execution = await service.record_firing(
        created.id,
        workflow_id=workflow_id,
        workflow_run_id=run_id,
        status=ScheduleRunStatus.RUNNING,
        next_run_at=None,
    )
    await service.update_execution_status(execution.id, status=ScheduleRunStatus.COMPLETED)
    await service.update_last_status(created.id, status=ScheduleRunStatus.COMPLETED)

    executions = await service.find_executions_by_schedule_id(created.id)
    assert executions[0].status == ScheduleRunStatus.COMPLETED
    refreshed = await service.get_schedule(created.id)
    assert refreshed.last_status == ScheduleRunStatus.COMPLETED


async def test_list_all_executions_returns_newest_first(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    await service.record_firing(
        created.id,
        workflow_id=workflow_id,
        workflow_run_id=uuid4(),
        status=ScheduleRunStatus.RUNNING,
        next_run_at=None,
    )
    await service.record_firing(
        created.id,
        workflow_id=workflow_id,
        workflow_run_id=uuid4(),
        status=ScheduleRunStatus.RUNNING,
        next_run_at=None,
    )
    executions, total = await service.list_all_executions(offset=0, limit=10)
    assert total == 2
    assert len(executions) == 2


async def test_delete_executions_removes_all_rows_for_a_schedule(
    service: ScheduleService, workflow_id: UUID
) -> None:
    created = await service.register_schedule(_cron_request(workflow_id=workflow_id))
    await service.record_firing(
        created.id,
        workflow_id=workflow_id,
        workflow_run_id=uuid4(),
        status=ScheduleRunStatus.RUNNING,
        next_run_at=None,
    )
    await service.delete_executions(created.id)
    remaining = await service.find_executions_by_schedule_id(created.id)
    assert remaining == []


async def test_get_schedule_names_batch_resolves(
    service: ScheduleService, workflow_id: UUID
) -> None:
    first = await service.register_schedule(_cron_request(workflow_id=workflow_id, name="First"))
    second = await service.register_schedule(_cron_request(workflow_id=workflow_id, name="Second"))
    names = await service.get_schedule_names([first.id, second.id])
    assert names == {first.id: "First", second.id: "Second"}
