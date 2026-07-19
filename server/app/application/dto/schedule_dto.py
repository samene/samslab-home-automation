"""Schedule data transfer objects: the only schedule shape REST controllers ever see.

Independent of the SQLAlchemy ``Schedule``/``ScheduleExecution`` models. Built
exclusively by ``app.application.mappers.schedule_mapper``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domains.schedules.models import ScheduleRunStatus, ScheduleType


class ScheduleDTO(BaseModel):
    """A schedule's full definition, with denormalized bookkeeping fields."""

    id: UUID
    workflow_id: UUID
    # Resolved fresh on every read (never persisted alongside it) so a later
    # workflow rename is reflected immediately — same convention as
    # SnapshotDTO.workflow_name.
    workflow_name: str | None = None
    name: str
    description: str | None
    enabled: bool
    schedule_type: ScheduleType
    cron_expression: str | None
    run_at: datetime | None
    timezone: str
    run_count: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_status: ScheduleRunStatus | None
    created_at: datetime
    updated_at: datetime


class SchedulePageDTO(BaseModel):
    """A bounded, paginated page of schedules."""

    items: list[ScheduleDTO]
    total: int
    offset: int
    limit: int


class ScheduleExecutionDTO(BaseModel):
    """One record of a schedule firing — backs History's "Manual vs Scheduled" correlation."""

    id: UUID
    schedule_id: UUID
    schedule_name: str | None = None
    workflow_id: UUID
    workflow_run_id: UUID | None
    triggered_at: datetime
    status: ScheduleRunStatus
    error_message: str | None


class ScheduleExecutionPageDTO(BaseModel):
    """A bounded, paginated page of schedule executions, newest first."""

    items: list[ScheduleExecutionDTO]
    total: int
    offset: int
    limit: int
