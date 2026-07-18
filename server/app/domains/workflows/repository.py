"""SQLAlchemy repository implementing all Workflows persistence operations.

Step trees and run/step-run history are fetched flat (one query each,
ordered by ``position``/``started_at``) rather than through navigable ORM
relationships — see ``models.py``'s module docstring for why. Reassembling
the tree shape is the application layer's job (``workflow_mapper.py``), not
this repository's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStep,
    WorkflowStepRun,
    WorkflowStepRunStatus,
)
from app.domains.workflows.schemas import WorkflowStepCreate


class WorkflowRepository:
    """Persist and query workflows without leaking SQLAlchemy into application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    @staticmethod
    def _active_workflows() -> Select[tuple[Workflow]]:
        return select(Workflow).where(Workflow.deleted_at.is_(None))

    async def create(self, workflow: Workflow, steps: list[WorkflowStepCreate]) -> Workflow:
        """Stage a new workflow and its full step tree for commit."""
        self._session.add(workflow)
        await self._session.flush()
        await self._insert_step_list(workflow.id, None, steps)
        await self._session.flush()
        return workflow

    async def replace_steps(self, workflow: Workflow, steps: list[WorkflowStepCreate]) -> None:
        """Atomically clear and recreate a workflow's entire step tree."""
        await self._session.execute(
            delete(WorkflowStep).where(WorkflowStep.workflow_id == workflow.id)
        )
        await self._session.flush()
        await self._insert_step_list(workflow.id, None, steps)
        await self._session.flush()

    async def _insert_step_list(
        self, workflow_id: UUID, parent_step_id: UUID | None, steps: list[WorkflowStepCreate]
    ) -> None:
        """Recursively insert an ordered step list, flushing per-node to get generated ids."""
        for position, step_input in enumerate(steps):
            step = WorkflowStep(
                workflow_id=workflow_id,
                parent_step_id=parent_step_id,
                position=position,
                step_type=step_input.step_type,
                command_type=step_input.command_type,
                sleep_seconds=step_input.sleep_seconds,
                group_mode=step_input.group_mode,
            )
            self._session.add(step)
            await self._session.flush()
            if step_input.children:
                await self._insert_step_list(workflow_id, step.id, step_input.children)

    async def update(self, workflow: Workflow, values: dict[str, object]) -> Workflow:
        """Apply explicitly approved mutable values to a workflow."""
        for name, value in values.items():
            setattr(workflow, name, value)
        await self._session.flush()
        await self._session.refresh(workflow)
        return workflow

    async def delete(self, workflow: Workflow) -> None:
        """Soft-delete a workflow while preserving its run history for audit."""
        workflow.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def find_by_id(self, workflow_id: UUID) -> Workflow | None:
        """Find one active workflow by UUID."""
        result = await self._session.execute(
            self._active_workflows().where(Workflow.id == workflow_id)
        )
        return result.scalar_one_or_none()

    async def find_all(self, *, offset: int, limit: int) -> tuple[list[Workflow], int]:
        """List active workflows with bounded pagination."""
        count = await self._session.scalar(
            select(func.count(Workflow.id)).where(Workflow.deleted_at.is_(None))
        )
        result = await self._session.execute(
            self._active_workflows().order_by(Workflow.name).offset(offset).limit(limit)
        )
        return list(result.scalars()), count or 0

    async def find_names_by_ids(self, workflow_ids: list[UUID]) -> dict[UUID, str]:
        """Batch-resolve workflow names for display, one query, no N+1.

        Deliberately not scoped to active (non-soft-deleted) workflows — a
        snapshot naming a since-deleted workflow should still show its name.
        """
        if not workflow_ids:
            return {}
        result = await self._session.execute(
            select(Workflow.id, Workflow.name).where(Workflow.id.in_(workflow_ids))
        )
        return dict(result.tuples().all())

    async def find_steps(self, workflow_id: UUID) -> list[WorkflowStep]:
        """Return every step (all nesting levels) for one workflow, flat."""
        result = await self._session.execute(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.position)
        )
        return list(result.scalars())

    async def create_run(self, workflow_id: UUID) -> WorkflowRun:
        """Start a new execution record for a workflow."""
        run = WorkflowRun(workflow_id=workflow_id, status=WorkflowRunStatus.RUNNING)
        self._session.add(run)
        await self._session.flush()
        return run

    async def update_run_status(
        self,
        run: WorkflowRun,
        *,
        status: WorkflowRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
    ) -> WorkflowRun:
        """Transition a run to a new (typically terminal) status."""
        run.status = status
        if completed_at is not None:
            run.completed_at = completed_at
        if error_message is not None:
            run.error_message = error_message
        await self._session.flush()
        return run

    async def find_run(self, run_id: UUID) -> WorkflowRun | None:
        """Find one run by UUID."""
        result = await self._session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        return result.scalar_one_or_none()

    async def find_latest_run(self, workflow_id: UUID) -> WorkflowRun | None:
        """Return a workflow's most recently started run, if any."""
        result = await self._session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_interrupted_runs(self) -> list[WorkflowRun]:
        """Return every run still marked RUNNING — used by the startup reconciliation sweep."""
        result = await self._session.execute(
            select(WorkflowRun).where(WorkflowRun.status == WorkflowRunStatus.RUNNING)
        )
        return list(result.scalars())

    async def create_step_run(
        self, run_id: UUID, step_id: UUID, *, status: WorkflowStepRunStatus
    ) -> WorkflowStepRun:
        """Start a new per-step execution record within a run."""
        step_run = WorkflowStepRun(workflow_run_id=run_id, workflow_step_id=step_id, status=status)
        self._session.add(step_run)
        await self._session.flush()
        return step_run

    async def update_step_run(
        self,
        step_run: WorkflowStepRun,
        *,
        status: WorkflowStepRunStatus,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        command_id: UUID | None = None,
        error_message: str | None = None,
    ) -> WorkflowStepRun:
        """Transition a step run's status and optionally attach its command/outcome."""
        step_run.status = status
        if started_at is not None:
            step_run.started_at = started_at
        if completed_at is not None:
            step_run.completed_at = completed_at
        if command_id is not None:
            step_run.command_id = command_id
        if error_message is not None:
            step_run.error_message = error_message
        await self._session.flush()
        return step_run

    async def find_step_runs(self, run_id: UUID) -> list[WorkflowStepRun]:
        """Return every step run (all nesting levels) for one workflow run, flat."""
        result = await self._session.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == run_id)
        )
        return list(result.scalars())

    async def find_step_run(self, step_run_id: UUID) -> WorkflowStepRun | None:
        """Find one step run by UUID."""
        result = await self._session.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.id == step_run_id)
        )
        return result.scalar_one_or_none()

    async def record_run_outcome(
        self,
        workflow_id: UUID,
        *,
        status: WorkflowRunStatus,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        """Update a workflow's denormalized last-run summary fields after a run finishes."""
        workflow = await self.find_by_id(workflow_id)
        if workflow is None:
            return
        workflow.run_count += 1
        workflow.last_run_at = completed_at
        workflow.last_run_status = status
        workflow.last_run_duration_ms = duration_ms
        await self._session.flush()
