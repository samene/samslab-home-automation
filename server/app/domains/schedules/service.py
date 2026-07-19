"""Transactional Schedules application service and business invariants.

Pure persistence only — registering/unregistering the live APScheduler job,
and calling ``WorkflowApplicationService.run_workflow`` when a schedule
fires, are cross-domain/infrastructure concerns that live in
``app.application.services.schedule_service.ScheduleApplicationService`` and
``app.scheduler.scheduler.WorkflowScheduler``, never here — mirrors how the
Workflows domain's own ``WorkflowService`` never touches the Command
Framework directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.domains.schedules.exceptions import ScheduleNotFound
from app.domains.schedules.models import Schedule, ScheduleExecution, ScheduleRunStatus
from app.domains.schedules.repository import ScheduleRepository
from app.domains.schedules.schemas import ScheduleCreate, ScheduleUpdate


class ScheduleService:
    """Coordinate Schedule definition and bookkeeping use cases without exposing persistence."""

    def __init__(self, repository: ScheduleRepository) -> None:
        """Inject the repository that owns schedule persistence operations."""
        self._repository = repository

    async def register_schedule(self, request: ScheduleCreate) -> Schedule:
        """Persist a new schedule."""
        schedule = Schedule(
            workflow_id=request.workflow_id,
            name=request.name,
            description=request.description,
            enabled=request.enabled,
            schedule_type=request.schedule_type,
            cron_expression=request.cron_expression,
            run_at=request.run_at,
            timezone=request.timezone,
        )
        return await self._repository.create(schedule)

    async def update_schedule(self, schedule_id: UUID, request: ScheduleUpdate) -> Schedule:
        """Replace a schedule's fields wholesale."""
        schedule = await self.get_schedule(schedule_id)
        return await self._repository.update(
            schedule,
            {
                "workflow_id": request.workflow_id,
                "name": request.name,
                "description": request.description,
                "enabled": request.enabled,
                "schedule_type": request.schedule_type,
                "cron_expression": request.cron_expression,
                "run_at": request.run_at,
                "timezone": request.timezone,
            },
        )

    async def get_schedule(self, schedule_id: UUID) -> Schedule:
        """Return an active schedule or raise the domain's not-found error."""
        schedule = await self._repository.find_by_id(schedule_id)
        if schedule is None:
            raise ScheduleNotFound(f"Schedule '{schedule_id}' was not found")
        return schedule

    async def list_schedules(
        self, *, offset: int, limit: int, enabled: bool | None, workflow_id: UUID | None
    ) -> tuple[list[Schedule], int]:
        """List active schedules, soonest next run first, bounded pagination."""
        return await self._repository.find_all(
            offset=offset, limit=limit, enabled=enabled, workflow_id=workflow_id
        )

    async def list_enabled(self) -> list[Schedule]:
        """Return every enabled schedule — used to reload the live scheduler at startup."""
        return await self._repository.find_enabled()

    async def get_schedule_names(self, schedule_ids: list[UUID]) -> dict[UUID, str]:
        """Batch-resolve schedule names for display, e.g. a History entry's "via" label."""
        return await self._repository.find_names_by_ids(schedule_ids)

    async def delete(self, schedule_id: UUID) -> None:
        """Soft-delete a schedule so its firing history remains auditable."""
        schedule = await self.get_schedule(schedule_id)
        await self._repository.delete(schedule)

    async def set_next_run_at(self, schedule_id: UUID, next_run_at: datetime | None) -> Schedule:
        """Persist the live scheduler's freshly computed next fire time."""
        schedule = await self.get_schedule(schedule_id)
        return await self._repository.update(schedule, {"next_run_at": next_run_at})

    async def set_enabled(self, schedule_id: UUID, *, enabled: bool) -> Schedule:
        """Flip a schedule's enabled flag; ``next_run_at`` is cleared when disabling."""
        schedule = await self.get_schedule(schedule_id)
        values: dict[str, object] = {"enabled": enabled}
        if not enabled:
            values["next_run_at"] = None
        return await self._repository.update(schedule, values)

    async def record_firing(
        self,
        schedule_id: UUID,
        *,
        workflow_id: UUID,
        workflow_run_id: UUID | None,
        status: ScheduleRunStatus,
        next_run_at: datetime | None,
        error_message: str | None = None,
    ) -> tuple[Schedule, ScheduleExecution]:
        """Bump a schedule's denormalized bookkeeping and record the firing itself.

        Mirrors ``WorkflowRepository.record_run_outcome`` — pure bookkeeping,
        no cross-domain orchestration (that already happened by the time the
        application layer calls this, having already invoked
        ``WorkflowApplicationService.run_workflow``).
        """
        schedule = await self.get_schedule(schedule_id)
        now = datetime.now(UTC)
        updated = await self._repository.update(
            schedule,
            {
                "run_count": schedule.run_count + 1,
                "last_run_at": now,
                "last_status": status,
                "next_run_at": next_run_at,
            },
        )
        execution = await self._repository.create_execution(
            schedule_id=schedule_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            status=status,
            error_message=error_message,
        )
        return updated, execution

    async def update_execution_status(
        self, execution_id: UUID, *, status: ScheduleRunStatus
    ) -> None:
        """Update one firing's outcome once its triggered workflow run reaches a terminal state."""
        execution = await self._repository.find_execution(execution_id)
        if execution is None:
            return
        await self._repository.update_execution_status(execution, status=status)

    async def update_last_status(self, schedule_id: UUID, *, status: ScheduleRunStatus) -> None:
        """Update a schedule's own denormalized last_status once its run finishes."""
        schedule = await self._repository.find_by_id(schedule_id)
        if schedule is None:
            return
        await self._repository.update(schedule, {"last_status": status})

    async def list_all_executions(
        self, *, offset: int, limit: int
    ) -> tuple[list[ScheduleExecution], int]:
        """List every schedule firing across all schedules, newest first."""
        return await self._repository.find_all_executions(offset=offset, limit=limit)

    async def find_executions_by_schedule_id(self, schedule_id: UUID) -> list[ScheduleExecution]:
        """Return every firing this schedule has ever produced — used by cascade-delete."""
        return await self._repository.find_executions_by_schedule_id(schedule_id)

    async def delete_executions(self, schedule_id: UUID) -> None:
        """Hard-delete a schedule's own firing records."""
        await self._repository.delete_executions_by_schedule_id(schedule_id)
