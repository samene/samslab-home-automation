"""Mapping from Schedules persistence entities to application DTOs."""

from __future__ import annotations

from app.application.dto.schedule_dto import (
    ScheduleDTO,
    ScheduleExecutionDTO,
)
from app.domains.schedules.models import Schedule, ScheduleExecution


def to_schedule_dto(schedule: Schedule, *, workflow_name: str | None = None) -> ScheduleDTO:
    """Map a persisted schedule's own fields."""
    return ScheduleDTO(
        id=schedule.id,
        workflow_id=schedule.workflow_id,
        workflow_name=workflow_name,
        name=schedule.name,
        description=schedule.description,
        enabled=schedule.enabled,
        schedule_type=schedule.schedule_type,
        cron_expression=schedule.cron_expression,
        run_at=schedule.run_at,
        timezone=schedule.timezone,
        run_count=schedule.run_count,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        last_status=schedule.last_status,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def to_schedule_execution_dto(
    execution: ScheduleExecution, *, schedule_name: str | None = None
) -> ScheduleExecutionDTO:
    """Map one firing record."""
    return ScheduleExecutionDTO(
        id=execution.id,
        schedule_id=execution.schedule_id,
        schedule_name=schedule_name,
        workflow_id=execution.workflow_id,
        workflow_run_id=execution.workflow_run_id,
        triggered_at=execution.triggered_at,
        status=execution.status,
        error_message=execution.error_message,
    )
