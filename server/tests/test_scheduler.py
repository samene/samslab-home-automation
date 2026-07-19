"""Tests for WorkflowScheduler — the live, APScheduler-backed trigger.

Real short-interval triggers and real ``asyncio`` waits throughout, no
mocked clock — the same style established by
``test_dispatcher_lifecycle.py``/``test_dispatcher_integration.py`` for the
Command Dispatcher's own background loops.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.database import Database
from app.domains.schedules.models import Schedule, ScheduleType
from app.domains.schedules.repository import ScheduleRepository
from app.domains.schedules.schemas import ScheduleCreate
from app.domains.schedules.service import ScheduleService
from app.domains.workflows.models import WorkflowStepType
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowCreate, WorkflowStepCreate
from app.domains.workflows.service import WorkflowService
from app.scheduler.scheduler import WorkflowScheduler


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def workflow_id(database: Database) -> UUID:
    """Persist one real workflow a schedule can reference."""
    async with database.session_factory() as session:
        service = WorkflowService(WorkflowRepository(session))
        workflow = await service.register_workflow(
            WorkflowCreate(
                name="Test workflow",
                steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=1)],
            )
        )
        await session.commit()
        return workflow.id


async def _create_schedule(database: Database, workflow_id: UUID, **overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workflow_id": workflow_id,
        "name": "Test schedule",
        "enabled": True,
        "schedule_type": ScheduleType.CRON,
        "cron_expression": "*/5 * * * *",
        "timezone": "UTC",
    }
    defaults.update(overrides)
    async with database.session_factory() as session:
        service = ScheduleService(ScheduleRepository(session))
        schedule = await service.register_schedule(ScheduleCreate(**defaults))
        await session.commit()
        return schedule


class _FakeOnFire:
    """Records every schedule_id fired and signals the first one via an event."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.event = asyncio.Event()

    async def __call__(self, schedule_id: UUID) -> None:
        self.calls.append(schedule_id)
        self.event.set()


async def test_start_is_a_noop_without_a_database() -> None:
    scheduler = WorkflowScheduler(database=None)
    await scheduler.start(on_fire=_FakeOnFire())
    assert scheduler.is_running is False


async def test_start_is_idempotent(database: Database) -> None:
    scheduler = WorkflowScheduler(database=database)
    await scheduler.start(on_fire=_FakeOnFire())
    await scheduler.start(on_fire=_FakeOnFire())  # second call is a no-op
    assert scheduler.is_running is True
    await scheduler.stop()


async def test_stop_is_a_noop_when_not_running() -> None:
    scheduler = WorkflowScheduler(database=None)
    await scheduler.stop()  # must not raise
    assert scheduler.is_running is False


async def test_register_and_unregister(database: Database, workflow_id: UUID) -> None:
    scheduler = WorkflowScheduler(database=database)
    await scheduler.start(on_fire=_FakeOnFire())
    try:
        schedule = await _create_schedule(database, workflow_id)
        scheduler.register(schedule)
        assert scheduler.next_run_time(schedule.id) is not None
        scheduler.unregister(schedule.id)
        assert scheduler.next_run_time(schedule.id) is None
    finally:
        await scheduler.stop()


async def test_unregister_tolerates_an_already_gone_job(database: Database) -> None:
    scheduler = WorkflowScheduler(database=database)
    await scheduler.start(on_fire=_FakeOnFire())
    try:
        scheduler.unregister(uuid4())  # never registered — must not raise
    finally:
        await scheduler.stop()


async def test_next_run_time_is_none_before_start(database: Database, workflow_id: UUID) -> None:
    scheduler = WorkflowScheduler(database=database)
    schedule = await _create_schedule(database, workflow_id)
    assert scheduler.next_run_time(schedule.id) is None


async def test_reload_on_startup_registers_every_enabled_schedule(
    database: Database, workflow_id: UUID
) -> None:
    """This is "Reload all enabled schedules automatically" on startup."""
    enabled = await _create_schedule(database, workflow_id, name="Enabled")
    disabled = await _create_schedule(database, workflow_id, name="Disabled", enabled=False)

    scheduler = WorkflowScheduler(database=database)
    await scheduler.start(on_fire=_FakeOnFire())
    try:
        assert scheduler.next_run_time(enabled.id) is not None
        assert scheduler.next_run_time(disabled.id) is None
    finally:
        await scheduler.stop()


async def test_reload_on_startup_persists_a_fresh_next_run_at_for_each_reloaded_schedule(
    database: Database, workflow_id: UUID
) -> None:
    """A restart must refresh next_run_at in the DB, not leave it stale — confirmed live."""
    schedule = await _create_schedule(database, workflow_id)

    scheduler = WorkflowScheduler(database=database)
    await scheduler.start(on_fire=_FakeOnFire())
    try:
        async with database.session_factory() as session:
            refreshed = await ScheduleService(ScheduleRepository(session)).get_schedule(schedule.id)
        assert refreshed.next_run_at is not None
        live_next_run = scheduler.next_run_time(schedule.id)
        assert live_next_run is not None
        # SQLite drops tzinfo on round-trip (unlike Postgres) — compare naive.
        assert refreshed.next_run_at.replace(tzinfo=UTC) == live_next_run
    finally:
        await scheduler.stop()


async def test_a_registered_one_time_job_actually_fires(
    database: Database, workflow_id: UUID
) -> None:
    """Real, short (~50ms) wait; asserts on_fire was actually invoked."""
    scheduler = WorkflowScheduler(database=database)
    on_fire = _FakeOnFire()
    await scheduler.start(on_fire=on_fire)
    try:
        run_at = datetime.now(UTC) + timedelta(milliseconds=50)
        schedule = await _create_schedule(
            database,
            workflow_id,
            schedule_type=ScheduleType.ONE_TIME,
            cron_expression=None,
            run_at=run_at,
        )
        scheduler.register(schedule)
        await asyncio.wait_for(on_fire.event.wait(), timeout=3.0)
        assert on_fire.calls == [schedule.id]
    finally:
        await scheduler.stop()


async def test_one_time_job_is_automatically_removed_from_the_live_jobstore_after_firing(
    database: Database, workflow_id: UUID
) -> None:
    scheduler = WorkflowScheduler(database=database)
    on_fire = _FakeOnFire()
    await scheduler.start(on_fire=on_fire)
    try:
        run_at = datetime.now(UTC) + timedelta(milliseconds=50)
        schedule = await _create_schedule(
            database,
            workflow_id,
            schedule_type=ScheduleType.ONE_TIME,
            cron_expression=None,
            run_at=run_at,
        )
        scheduler.register(schedule)
        await asyncio.wait_for(on_fire.event.wait(), timeout=3.0)
        await asyncio.sleep(0.05)  # let APScheduler finish its own job-removal bookkeeping
        assert scheduler.next_run_time(schedule.id) is None
    finally:
        await scheduler.stop()


async def test_scheduler_restart_reregisters_enabled_schedules(
    database: Database, workflow_id: UUID
) -> None:
    """Mirrors test_dispatcher_worker_lifecycle_survives_stop_and_restart's exact shape."""
    schedule = await _create_schedule(database, workflow_id)

    first = WorkflowScheduler(database=database)
    await first.start(on_fire=_FakeOnFire())
    assert first.next_run_time(schedule.id) is not None
    await first.stop()
    assert first.is_running is False

    second = WorkflowScheduler(database=database)
    try:
        await second.start(on_fire=_FakeOnFire())
        assert second.next_run_time(schedule.id) is not None
    finally:
        await second.stop()
