"""SQLAlchemy persistence models owned exclusively by the Schedules domain.

A Schedule is purely a trigger: it names a ``workflow_id`` to run and either
a one-time ``run_at`` or a recurring ``cron_expression``, plus the same
denormalized last-run summary fields ``Workflow`` itself carries
(``run_count``/``last_run_at``/``last_run_status``) so the list page never
joins anything, plus one Schedules-only field a Workflow never needed:
``next_run_at``. ``ScheduleExecution`` is the per-firing audit trail — one
row per time this schedule ever actually triggered a workflow run — used
both to correlate "Manual vs Scheduled" in History (via the run's
``workflow_run_id``, matched against a Command's own ``correlation_id``) and
to know exactly which rows a cascade-delete needs to remove.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScheduleType(StrEnum):
    """Whether a schedule fires once at a specific time or on a recurring cadence."""

    ONE_TIME = "ONE_TIME"
    CRON = "CRON"


class ScheduleRunStatus(StrEnum):
    """Outcome of one schedule firing — mirrors ``WorkflowRunStatus``'s shape."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Schedule(Base):
    """A trigger that fires exactly one Workflow — never a Command, never hardware."""

    __tablename__ = "schedules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # No cascade, cross-domain — same convention as Snapshot.workflow_id: a
    # schedule's own lifecycle never controls (and is never controlled by)
    # the workflow it targets. Workflows are only ever soft-deleted, so this
    # FK never dangles.
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    schedule_type: Mapped[ScheduleType] = mapped_column(
        Enum(ScheduleType, native_enum=False, length=20)
    )
    # Populated per schedule_type, enforced by ScheduleCreate's pydantic
    # validation (mirrors WorkflowStep's own command_type/sleep_seconds split
    # — a schema-level invariant, not a DB constraint).
    cron_expression: Mapped[str | None] = mapped_column(String(120), nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # Denormalized, mirroring Workflow.run_count/last_run_at/last_run_status
    # exactly, plus next_run_at — a field only a Schedule needs, since a
    # Workflow definition itself has no notion of a future trigger time.
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_status: Mapped[ScheduleRunStatus | None] = mapped_column(
        Enum(ScheduleRunStatus, native_enum=False, length=20), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class ScheduleExecution(Base):
    """One record of a schedule actually firing — the "Future execution records" artifact.

    Fully owned by this domain (cascade FK to its own parent ``Schedule``),
    unlike the cross-domain ``workflow_id``/``workflow_run_id`` columns below,
    which are deliberately no-cascade for the same reason every other
    cross-domain FK in this codebase is: a workflow/run is never hard-deleted
    by this app's own code, so these never dangle.
    """

    __tablename__ = "schedule_executions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    schedule_id: Mapped[UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    # Null only in the narrow window between "run_workflow was invoked" and
    # "its response was persisted" — in practice always set before commit,
    # since the caller has the run id in hand synchronously.
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=True, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[ScheduleRunStatus] = mapped_column(
        Enum(ScheduleRunStatus, native_enum=False, length=20), index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
