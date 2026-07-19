"""Typed API contracts and validation rules for the Schedules domain."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domains.schedules.models import ScheduleType
from app.domains.schedules.validators import validate_cron_expression, validate_timezone


class ScheduleCreate(BaseModel):
    """Input for defining a new schedule, or replacing an existing one wholesale."""

    workflow_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    schedule_type: ScheduleType
    cron_expression: str | None = Field(default=None, max_length=120)
    run_at: datetime | None = None
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_shape(self) -> ScheduleCreate:
        """Enforce that each schedule carries exactly the fields its type needs."""
        validate_timezone(self.timezone)
        if self.schedule_type is ScheduleType.CRON:
            if not self.cron_expression:
                raise ValueError("cron_expression is required for a CRON schedule")
            validate_cron_expression(self.cron_expression, self.timezone)
        else:
            if self.run_at is None:
                raise ValueError("run_at is required for a ONE_TIME schedule")
            if self.run_at.tzinfo is None:
                # A naive value came from a <input type="datetime-local"> paired
                # with the separate timezone field — interpret it in that zone
                # rather than silently assuming UTC.
                self.run_at = self.run_at.replace(tzinfo=validate_timezone(self.timezone))
        return self


class ScheduleUpdate(ScheduleCreate):
    """Same shape as create — a PUT always replaces the full definition."""
