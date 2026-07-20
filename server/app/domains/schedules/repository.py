"""SQLAlchemy repository implementing all Schedules persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedules.models import Schedule, ScheduleExecution, ScheduleRunStatus


class ScheduleRepository:
    """Persist and query schedules without leaking SQLAlchemy into application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    @staticmethod
    def _active_schedules() -> Select[tuple[Schedule]]:
        return select(Schedule).where(Schedule.deleted_at.is_(None))

    async def create(self, schedule: Schedule) -> Schedule:
        """Stage a new schedule for commit."""
        self._session.add(schedule)
        await self._session.flush()
        return schedule

    async def update(self, schedule: Schedule, values: dict[str, object]) -> Schedule:
        """Apply explicitly approved mutable values to a schedule."""
        for name, value in values.items():
            setattr(schedule, name, value)
        await self._session.flush()
        await self._session.refresh(schedule)
        return schedule

    async def delete(self, schedule: Schedule) -> None:
        """Soft-delete a schedule while preserving its execution history for audit."""
        schedule.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def find_by_id(self, schedule_id: UUID) -> Schedule | None:
        """Find one active schedule by UUID."""
        result = await self._session.execute(
            self._active_schedules().where(Schedule.id == schedule_id)
        )
        return result.scalar_one_or_none()

    async def find_all(
        self, *, offset: int, limit: int, enabled: bool | None, workflow_id: UUID | None
    ) -> tuple[list[Schedule], int]:
        """List active schedules, soonest next run first (nulls last), bounded pagination."""
        filters: list[ColumnElement[bool]] = [Schedule.deleted_at.is_(None)]
        if enabled is not None:
            filters.append(Schedule.enabled == enabled)
        if workflow_id is not None:
            filters.append(Schedule.workflow_id == workflow_id)
        count = await self._session.scalar(select(func.count(Schedule.id)).where(*filters))
        result = await self._session.execute(
            select(Schedule)
            .where(*filters)
            .order_by(Schedule.next_run_at.is_(None), Schedule.next_run_at)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), count or 0

    async def find_enabled(self) -> list[Schedule]:
        """Return every enabled, active schedule — used to reload the live scheduler at startup."""
        result = await self._session.execute(
            self._active_schedules().where(Schedule.enabled.is_(True))
        )
        return list(result.scalars())

    async def find_names_by_ids(self, schedule_ids: list[UUID]) -> dict[UUID, str]:
        """Batch-resolve schedule names for display, one query, no N+1."""
        if not schedule_ids:
            return {}
        result = await self._session.execute(
            select(Schedule.id, Schedule.name).where(Schedule.id.in_(schedule_ids))
        )
        return dict(result.tuples().all())

    async def create_execution(
        self,
        *,
        schedule_id: UUID,
        workflow_id: UUID,
        workflow_run_id: UUID | None,
        status: ScheduleRunStatus,
        error_message: str | None = None,
    ) -> ScheduleExecution:
        """Record one schedule firing."""
        execution = ScheduleExecution(
            schedule_id=schedule_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            status=status,
            error_message=error_message,
        )
        self._session.add(execution)
        await self._session.flush()
        return execution

    async def update_execution_status(
        self, execution: ScheduleExecution, *, status: ScheduleRunStatus
    ) -> ScheduleExecution:
        """Update a firing's outcome once its triggered workflow run reaches a terminal state."""
        execution.status = status
        await self._session.flush()
        return execution

    async def find_execution(self, execution_id: UUID) -> ScheduleExecution | None:
        """Find one execution record by UUID."""
        result = await self._session.execute(
            select(ScheduleExecution).where(ScheduleExecution.id == execution_id)
        )
        return result.scalar_one_or_none()

    async def find_executions_by_schedule_id(self, schedule_id: UUID) -> list[ScheduleExecution]:
        """Return every firing this schedule has ever produced — used by cascade-delete."""
        result = await self._session.execute(
            select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)
        )
        return list(result.scalars())

    async def find_all_executions(
        self, *, offset: int, limit: int
    ) -> tuple[list[ScheduleExecution], int]:
        """List every schedule firing across all schedules, newest first — backs History correlation."""
        count = await self._session.scalar(select(func.count(ScheduleExecution.id)))
        result = await self._session.execute(
            select(ScheduleExecution)
            .order_by(ScheduleExecution.triggered_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), count or 0

    async def delete_executions_by_schedule_id(self, schedule_id: UUID) -> None:
        """Hard-delete a schedule's own firing records — its own domain's table, no exception needed."""
        await self._session.execute(
            delete(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)
        )
        await self._session.flush()
