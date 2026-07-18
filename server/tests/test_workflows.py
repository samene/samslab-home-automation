"""Repository and service tests for the Workflows domain."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.database import Database
from app.domains.workflows.exceptions import WorkflowNotFound
from app.domains.workflows.models import (
    WorkflowRunStatus,
    WorkflowStepRunStatus,
    WorkflowStepType,
)
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowCreate, WorkflowStepCreate, WorkflowUpdate
from app.domains.workflows.service import WorkflowService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database for each domain test."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'workflows.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def service(database: Database) -> AsyncIterator[WorkflowService]:
    """Provide a transaction-scoped service for repository/service tests."""
    async with database.session_factory() as session:
        yield WorkflowService(WorkflowRepository(session))
        try:
            await session.commit()
        except Exception:
            await session.rollback()


def _simple_request(**overrides: object) -> WorkflowCreate:
    defaults: dict[str, object] = {
        "name": "Evening Watering",
        "description": "Stream snapshot then stop",
        "enabled": True,
        "steps": [
            WorkflowStepCreate(step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"),
            WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=5),
        ],
    }
    defaults.update(overrides)
    return WorkflowCreate(**defaults)


def _with_parallel_group() -> WorkflowCreate:
    return WorkflowCreate(
        name="Multi-camera burst",
        steps=[
            WorkflowStepCreate(step_type=WorkflowStepType.COMMAND, command_type="camera.stream.start"),
            WorkflowStepCreate(
                step_type=WorkflowStepType.GROUP,
                group_mode="PARALLEL",
                children=[
                    WorkflowStepCreate(step_type=WorkflowStepType.COMMAND, command_type="camera.snapshot"),
                    WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=2),
                ],
            ),
            WorkflowStepCreate(step_type=WorkflowStepType.COMMAND, command_type="camera.stream.stop"),
        ],
    )


async def test_register_workflow_persists_name_and_steps(service: WorkflowService) -> None:
    workflow = await service.register_workflow(_simple_request())

    assert workflow.name == "Evening Watering"
    assert workflow.enabled is True
    assert workflow.run_count == 0
    assert workflow.last_run_at is None


async def test_register_workflow_persists_a_flat_step_list(service: WorkflowService) -> None:
    workflow = await service.register_workflow(_simple_request())

    steps = await service._repository.find_steps(workflow.id)
    assert len(steps) == 2
    assert {step.step_type for step in steps} == {WorkflowStepType.COMMAND, WorkflowStepType.SLEEP}
    assert all(step.parent_step_id is None for step in steps)


async def test_register_workflow_persists_a_nested_parallel_group(service: WorkflowService) -> None:
    workflow = await service.register_workflow(_with_parallel_group())

    steps = await service._repository.find_steps(workflow.id)
    assert len(steps) == 5  # start, group, snapshot, sleep, stop

    top_level = [step for step in steps if step.parent_step_id is None]
    assert len(top_level) == 3

    group_step = next(step for step in top_level if step.step_type == WorkflowStepType.GROUP)
    children = [step for step in steps if step.parent_step_id == group_step.id]
    assert len(children) == 2
    assert group_step.group_mode == "PARALLEL"


async def test_get_workflow_raises_not_found_for_missing_id(service: WorkflowService) -> None:
    with pytest.raises(WorkflowNotFound):
        await service.get_workflow(uuid4())


async def test_update_workflow_atomically_replaces_the_step_tree(service: WorkflowService) -> None:
    workflow = await service.register_workflow(_simple_request())

    updated = await service.update_workflow(
        workflow.id,
        WorkflowUpdate(
            name="Evening Watering (v2)",
            steps=[WorkflowStepCreate(step_type=WorkflowStepType.SLEEP, sleep_seconds=10)],
        ),
    )

    assert updated.name == "Evening Watering (v2)"
    steps = await service._repository.find_steps(workflow.id)
    assert len(steps) == 1
    assert steps[0].sleep_seconds == 10


async def test_delete_soft_deletes_and_excludes_from_list_and_get(service: WorkflowService) -> None:
    workflow = await service.register_workflow(_simple_request())

    await service.delete(workflow.id)

    with pytest.raises(WorkflowNotFound):
        await service.get_workflow(workflow.id)
    items, total = await service.list_workflows(offset=0, limit=50)
    assert workflow.id not in {item.id for item in items}
    assert total == 0


async def test_list_workflows_paginates(service: WorkflowService) -> None:
    for index in range(3):
        await service.register_workflow(_simple_request(name=f"Workflow {index}"))

    page, total = await service.list_workflows(offset=0, limit=2)
    assert total == 3
    assert len(page) == 2


async def test_reconcile_interrupted_runs_fails_orphaned_running_rows(
    service: WorkflowService,
) -> None:
    workflow = await service.register_workflow(_simple_request())
    repository = service._repository
    run = await repository.create_run(workflow.id)
    assert run.status == WorkflowRunStatus.RUNNING

    reconciled_count = await service.reconcile_interrupted_runs()

    assert reconciled_count == 1
    refreshed_run = await repository.find_run(run.id)
    assert refreshed_run is not None
    assert refreshed_run.status == WorkflowRunStatus.FAILED
    assert refreshed_run.error_message == "interrupted by server restart"

    refreshed_workflow = await repository.find_by_id(workflow.id)
    assert refreshed_workflow is not None
    assert refreshed_workflow.run_count == 1
    assert refreshed_workflow.last_run_status == WorkflowRunStatus.FAILED


async def test_reconcile_interrupted_runs_is_a_noop_when_nothing_is_running(
    service: WorkflowService,
) -> None:
    assert await service.reconcile_interrupted_runs() == 0


async def test_step_run_lifecycle_via_repository(service: WorkflowService) -> None:
    workflow = await service.register_workflow(_simple_request())
    repository = service._repository
    steps = await repository.find_steps(workflow.id)
    run = await repository.create_run(workflow.id)

    step_run = await repository.create_step_run(
        run.id, steps[0].id, status=WorkflowStepRunStatus.RUNNING
    )
    assert step_run.status == WorkflowStepRunStatus.RUNNING

    completed = await repository.update_step_run(
        step_run,
        status=WorkflowStepRunStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        command_id=uuid4(),
    )
    assert completed.status == WorkflowStepRunStatus.COMPLETED
    assert completed.command_id is not None

    all_step_runs = await repository.find_step_runs(run.id)
    assert len(all_step_runs) == 1
