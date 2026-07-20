"""SQLAlchemy persistence models owned exclusively by the Workflows domain.

Deliberately no ORM relationships between ``Workflow``/``WorkflowStep`` or
``WorkflowRun``/``WorkflowStepRun`` — a step tree is arbitrarily nestable via
``WorkflowStep.parent_step_id`` (a plain self-referential FK column, not a
navigable relationship), so the repository fetches each table's rows flat
(one query, ordered by ``position``) and the application layer's mapper
reassembles the tree in plain Python. This avoids the cascade/eager-load
complexity of a self-referential ORM relationship for a shape that's simple
to rebuild from a flat list once, at read time.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WorkflowStepType(StrEnum):
    """What kind of work one step represents."""

    COMMAND = "COMMAND"
    SLEEP = "SLEEP"
    GROUP = "GROUP"


class WorkflowGroupMode(StrEnum):
    """How a GROUP step's children are executed relative to each other."""

    SERIAL = "SERIAL"
    PARALLEL = "PARALLEL"


class WorkflowRunStatus(StrEnum):
    """Lifecycle of one execution of a workflow."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WorkflowStepRunStatus(StrEnum):
    """Lifecycle of one step within one workflow run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Workflow(Base):
    """A named, ordered sequence of steps — the top-level executable unit."""

    __tablename__ = "workflows"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    # Denormalized onto the workflow row so the list page never needs a join
    # across every workflow's runs just to render "Last Run"/"Run Count".
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[WorkflowRunStatus | None] = mapped_column(
        Enum(WorkflowRunStatus, native_enum=False, length=20), nullable=True
    )
    last_run_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class WorkflowStep(Base):
    """One node in a workflow's step tree — a leaf (COMMAND/SLEEP) or a GROUP container."""

    __tablename__ = "workflow_steps"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    parent_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[WorkflowStepType] = mapped_column(
        Enum(WorkflowStepType, native_enum=False, length=20)
    )
    # Populated only for the matching step_type; enforced by WorkflowStepCreate's
    # pydantic validation, not a DB constraint (matches this codebase's general
    # preference for schema-level over check-constraint-level invariants).
    command_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sleep_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_mode: Mapped[WorkflowGroupMode | None] = mapped_column(
        Enum(WorkflowGroupMode, native_enum=False, length=20), nullable=True
    )


class WorkflowRun(Base):
    """One execution of a workflow — the audit/outcome trail, not a Job abstraction."""

    __tablename__ = "workflow_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[WorkflowRunStatus] = mapped_column(
        Enum(WorkflowRunStatus, native_enum=False, length=20), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowStepRun(Base):
    """One step's outcome within one workflow run."""

    __tablename__ = "workflow_step_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    workflow_step_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_steps.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[WorkflowStepRunStatus] = mapped_column(
        Enum(WorkflowStepRunStatus, native_enum=False, length=20), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # No cascade, cross-domain — same convention as snapshots.command_id: a
    # workflow step's own lifecycle never controls a command's lifecycle.
    command_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("commands.id"), nullable=True, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
