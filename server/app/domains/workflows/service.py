"""Transactional Workflows application service and business invariants.

Pure persistence and step-tree lifecycle only — creating/awaiting commands
for a Command Task, sleeping for a Sleep Task, and fanning out a Parallel
Group are all execution concerns that live in
``app.application.services.workflow_service.WorkflowApplicationService``,
never here (mirrors how Commands' own domain service never talks to
Devices — cross-domain orchestration is exclusively an application-layer job).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.domains.workflows.exceptions import WorkflowNotFound
from app.domains.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStep,
    WorkflowStepRun,
    WorkflowStepRunStatus,
)
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowCreate, WorkflowUpdate


def _duration_ms_since(started_at: datetime, ended_at: datetime) -> int:
    """SQLite drops tzinfo on round-trip (unlike Postgres); normalize before subtracting."""
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return int((ended_at - started_at).total_seconds() * 1000)


class WorkflowService:
    """Coordinate Workflow definition use cases without exposing persistence details."""

    def __init__(self, repository: WorkflowRepository) -> None:
        """Inject the repository that owns workflow persistence operations."""
        self._repository = repository

    async def register_workflow(self, request: WorkflowCreate) -> Workflow:
        """Persist a new workflow and its full step tree."""
        workflow = Workflow(
            name=request.name, description=request.description, enabled=request.enabled
        )
        return await self._repository.create(workflow, request.steps)

    async def update_workflow(self, workflow_id: UUID, request: WorkflowUpdate) -> Workflow:
        """Replace a workflow's fields and its entire step tree."""
        workflow = await self.get_workflow(workflow_id)
        await self._repository.update(
            workflow,
            {
                "name": request.name,
                "description": request.description,
                "enabled": request.enabled,
            },
        )
        await self._repository.replace_steps(workflow, request.steps)
        return workflow

    async def get_workflow(self, workflow_id: UUID) -> Workflow:
        """Return an active workflow or raise the domain's not-found error."""
        workflow = await self._repository.find_by_id(workflow_id)
        if workflow is None:
            raise WorkflowNotFound(f"Workflow '{workflow_id}' was not found")
        return workflow

    async def list_workflows(self, *, offset: int, limit: int) -> tuple[list[Workflow], int]:
        """List active workflows with bounded pagination."""
        return await self._repository.find_all(offset=offset, limit=limit)

    async def get_workflow_names(self, workflow_ids: list[UUID]) -> dict[UUID, str]:
        """Batch-resolve workflow names for display, e.g. a snapshot's "created by" note."""
        return await self._repository.find_names_by_ids(workflow_ids)

    async def delete(self, workflow_id: UUID) -> None:
        """Soft-delete a workflow so its run history remains auditable."""
        workflow = await self.get_workflow(workflow_id)
        await self._repository.delete(workflow)

    async def reconcile_interrupted_runs(self) -> int:
        """Fail every run still marked RUNNING at startup — it has no owning task anymore.

        Called once from the application lifespan, before anything else
        might observe a run stuck showing "running" forever after a crash
        or restart (the ``asyncio.Task`` driving it does not survive the
        process, even though the DB row does).
        """
        interrupted = await self._repository.find_interrupted_runs()
        now = datetime.now(UTC)
        for run in interrupted:
            await self._repository.update_run_status(
                run,
                status=WorkflowRunStatus.FAILED,
                completed_at=now,
                error_message="interrupted by server restart",
            )
            await self._repository.record_run_outcome(
                run.workflow_id,
                status=WorkflowRunStatus.FAILED,
                completed_at=now,
                duration_ms=_duration_ms_since(run.started_at, now),
            )
        return len(interrupted)

    # --- Execution bookkeeping ---------------------------------------------
    #
    # These are plain, ID-based CRUD primitives for workflow_runs/
    # workflow_step_runs — never returning/consuming a live ORM object across
    # calls, since the application layer's execution engine
    # (WorkflowApplicationService) opens a fresh session per operation, the
    # same way CameraApplicationService does. Orchestration itself (deciding
    # what runs when, waiting on commands, sleeping) stays entirely in that
    # application service — this is just the persistence these calls need.

    async def get_workflow_steps(self, workflow_id: UUID) -> list[WorkflowStep]:
        """Return every step (all nesting levels) for one workflow, flat."""
        return await self._repository.find_steps(workflow_id)

    async def create_run(self, workflow_id: UUID) -> WorkflowRun:
        """Start a new execution record for a workflow."""
        return await self._repository.create_run(workflow_id)

    async def get_run(self, run_id: UUID) -> WorkflowRun:
        """Return one run or raise the domain's not-found error."""
        run = await self._repository.find_run(run_id)
        if run is None:
            raise WorkflowNotFound(f"Workflow run '{run_id}' was not found")
        return run

    async def get_latest_run_with_step_runs(
        self, workflow_id: UUID
    ) -> tuple[WorkflowRun | None, list[WorkflowStepRun]]:
        """Return a workflow's most recent run plus its full step-run tree, if any."""
        run = await self._repository.find_latest_run(workflow_id)
        if run is None:
            return None, []
        return run, await self._repository.find_step_runs(run.id)

    async def finish_run(
        self, run_id: UUID, *, status: WorkflowRunStatus, error_message: str | None = None
    ) -> WorkflowRun:
        """Transition a run to a terminal status and update the workflow's denormalized summary."""
        run = await self.get_run(run_id)
        completed_at = datetime.now(UTC)
        updated = await self._repository.update_run_status(
            run, status=status, completed_at=completed_at, error_message=error_message
        )
        await self._repository.record_run_outcome(
            run.workflow_id,
            status=status,
            completed_at=completed_at,
            duration_ms=_duration_ms_since(run.started_at, completed_at),
        )
        return updated

    async def start_step_run(self, run_id: UUID, step_id: UUID) -> WorkflowStepRun:
        """Start a new per-step execution record within a run."""
        return await self._repository.create_step_run(
            run_id, step_id, status=WorkflowStepRunStatus.RUNNING
        )

    async def attach_command_to_step_run(self, step_run_id: UUID, command_id: UUID) -> WorkflowStepRun:
        """Record which command a RUNNING Command Task step is waiting on."""
        step_run = await self._get_step_run(step_run_id)
        return await self._repository.update_step_run(
            step_run, status=WorkflowStepRunStatus.RUNNING, command_id=command_id
        )

    async def finish_step_run(
        self,
        step_run_id: UUID,
        *,
        status: WorkflowStepRunStatus,
        error_message: str | None = None,
    ) -> WorkflowStepRun:
        """Transition a step run to a terminal status (COMPLETED/FAILED/CANCELLED)."""
        step_run = await self._get_step_run(step_run_id)
        return await self._repository.update_step_run(
            step_run,
            status=status,
            completed_at=datetime.now(UTC),
            error_message=error_message,
        )

    async def _get_step_run(self, step_run_id: UUID) -> WorkflowStepRun:
        step_run = await self._repository.find_step_run(step_run_id)
        if step_run is None:
            raise WorkflowNotFound(f"Workflow step run '{step_run_id}' was not found")
        return step_run
