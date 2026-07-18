"""Workflow data transfer objects: the only workflow shape REST controllers ever see.

Independent of the SQLAlchemy ``Workflow``/``WorkflowStep``/``WorkflowRun``/
``WorkflowStepRun`` models. Built exclusively by
``app.application.mappers.workflow_mapper``, which reassembles the flat,
DB-stored step/step-run rows into the nested trees below.

``WorkflowStepDTO``/``WorkflowStepRunDTO`` are this codebase's first
self-referential Pydantic models (a ``GROUP`` step's ``children`` are more
``WorkflowStepDTO`` instances) — verified safe under this project's
``from __future__ import annotations`` + Pydantic v2 convention by an
explicit round-trip test in ``test_application_dto.py``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domains.workflows.models import (
    WorkflowGroupMode,
    WorkflowRunStatus,
    WorkflowStepRunStatus,
    WorkflowStepType,
)


class WorkflowStepDTO(BaseModel):
    """One node in a workflow's step tree — a leaf or a GROUP container."""

    id: UUID
    step_type: WorkflowStepType
    command_type: str | None
    sleep_seconds: int | None
    group_mode: WorkflowGroupMode | None
    children: list[WorkflowStepDTO]


class WorkflowDTO(BaseModel):
    """A workflow's definition summary, with denormalized last-run fields."""

    id: UUID
    name: str
    description: str | None
    enabled: bool
    run_count: int
    last_run_at: datetime | None
    last_run_status: WorkflowRunStatus | None
    last_run_duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class WorkflowPageDTO(BaseModel):
    """A bounded, paginated page of workflows."""

    items: list[WorkflowDTO]
    total: int
    offset: int
    limit: int


class WorkflowStepRunDTO(BaseModel):
    """One step's outcome within one workflow run, mirroring the step tree's shape."""

    id: UUID | None
    workflow_step_id: UUID
    step_type: WorkflowStepType
    status: WorkflowStepRunStatus
    started_at: datetime | None
    completed_at: datetime | None
    command_id: UUID | None
    error_message: str | None
    children: list[WorkflowStepRunDTO]


class WorkflowRunDTO(BaseModel):
    """One execution of a workflow, with its full per-step status tree."""

    id: UUID
    workflow_id: UUID
    status: WorkflowRunStatus
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None
    step_runs: list[WorkflowStepRunDTO]


class WorkflowDetailDTO(WorkflowDTO):
    """A workflow's full definition plus its most recent execution, if any."""

    steps: list[WorkflowStepDTO]
    latest_run: WorkflowRunDTO | None
