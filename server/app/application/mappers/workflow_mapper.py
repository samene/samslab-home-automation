"""Mapping from Workflows persistence entities to application DTOs.

Steps and step-runs are stored flat (see ``domains/workflows/models.py``'s
module docstring); every tree-shaped DTO here is assembled in plain Python
from those flat lists — never from a navigable ORM relationship.
"""

from __future__ import annotations

from uuid import UUID

from app.application.dto.workflow_dto import (
    WorkflowDetailDTO,
    WorkflowDTO,
    WorkflowRunDTO,
    WorkflowStepDTO,
    WorkflowStepRunDTO,
)
from app.domains.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepRun,
    WorkflowStepRunStatus,
)


def to_workflow_dto(workflow: Workflow) -> WorkflowDTO:
    """Map a persisted workflow's own fields, without its step tree."""
    return WorkflowDTO(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        enabled=workflow.enabled,
        run_count=workflow.run_count,
        last_run_at=workflow.last_run_at,
        last_run_status=workflow.last_run_status,
        last_run_duration_ms=workflow.last_run_duration_ms,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def to_step_tree(steps: list[WorkflowStep], *, parent_step_id: UUID | None = None) -> list[WorkflowStepDTO]:
    """Rebuild the nested step tree from a flat, workflow-scoped list of rows."""
    children = sorted(
        (step for step in steps if step.parent_step_id == parent_step_id), key=lambda s: s.position
    )
    return [
        WorkflowStepDTO(
            id=step.id,
            step_type=step.step_type,
            command_type=step.command_type,
            sleep_seconds=step.sleep_seconds,
            group_mode=step.group_mode,
            children=to_step_tree(steps, parent_step_id=step.id),
        )
        for step in children
    ]


def to_step_run_tree(
    steps: list[WorkflowStep],
    step_runs_by_step_id: dict[UUID, WorkflowStepRun],
    *,
    parent_step_id: UUID | None = None,
) -> list[WorkflowStepRunDTO]:
    """Rebuild the nested step-run tree, mirroring the step tree's shape.

    A step with no matching row yet (hasn't started in this run) gets a
    synthetic PENDING placeholder rather than being omitted — the live
    Execution Status view needs to show every step, not just ones that have
    already run.
    """
    children = sorted(
        (step for step in steps if step.parent_step_id == parent_step_id), key=lambda s: s.position
    )
    result: list[WorkflowStepRunDTO] = []
    for step in children:
        step_run = step_runs_by_step_id.get(step.id)
        result.append(
            WorkflowStepRunDTO(
                id=step_run.id if step_run else None,
                workflow_step_id=step.id,
                step_type=step.step_type,
                status=step_run.status if step_run else WorkflowStepRunStatus.PENDING,
                started_at=step_run.started_at if step_run else None,
                completed_at=step_run.completed_at if step_run else None,
                command_id=step_run.command_id if step_run else None,
                error_message=step_run.error_message if step_run else None,
                children=to_step_run_tree(steps, step_runs_by_step_id, parent_step_id=step.id),
            )
        )
    return result


def to_workflow_run_dto(
    run: WorkflowRun, steps: list[WorkflowStep], step_runs: list[WorkflowStepRun]
) -> WorkflowRunDTO:
    """Map one execution and its per-step outcomes to a DTO."""
    step_runs_by_step_id = {step_run.workflow_step_id: step_run for step_run in step_runs}
    return WorkflowRunDTO(
        id=run.id,
        workflow_id=run.workflow_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_message=run.error_message,
        step_runs=to_step_run_tree(steps, step_runs_by_step_id),
    )


def to_workflow_detail_dto(
    workflow: Workflow,
    steps: list[WorkflowStep],
    *,
    latest_run: WorkflowRun | None,
    latest_run_step_runs: list[WorkflowStepRun],
) -> WorkflowDetailDTO:
    """Map a workflow, its step tree, and its most recent execution to a DTO."""
    summary = to_workflow_dto(workflow)
    return WorkflowDetailDTO(
        **summary.model_dump(),
        steps=to_step_tree(steps),
        latest_run=(
            to_workflow_run_dto(latest_run, steps, latest_run_step_runs)
            if latest_run is not None
            else None
        ),
    )
