"""Typed API contracts and validation rules for the Workflows domain.

A ``PUT`` always replaces a workflow's full step tree — there is no
incremental per-step CRUD, mirroring how the Device Registry's
``replace_capabilities`` atomically clears and re-inserts rather than
diffing individual capability rows.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domains.commands.validators import validate_command_type
from app.domains.workflows.models import WorkflowGroupMode, WorkflowStepType


class WorkflowStepCreate(BaseModel):
    """One node in a submitted step tree — a leaf (COMMAND/SLEEP) or a GROUP container.

    Recursive: a ``GROUP`` step's ``children`` are themselves
    ``WorkflowStepCreate`` instances, supporting arbitrarily nested groups at
    the schema level even though the v1 editor UI only ever builds one level
    of nesting — see ``docs/architecture/WORKFLOWS.md``.
    """

    step_type: WorkflowStepType
    command_type: str | None = Field(default=None, max_length=150)
    sleep_seconds: int | None = Field(default=None, gt=0)
    group_mode: WorkflowGroupMode | None = None
    children: list[WorkflowStepCreate] = Field(default_factory=list)

    @field_validator("command_type")
    @classmethod
    def validate_type(cls, value: str | None) -> str | None:
        """Reuse the Command domain's own type pattern rather than reinventing it."""
        if value is None:
            return None
        return validate_command_type(value)

    @model_validator(mode="after")
    def validate_shape(self) -> WorkflowStepCreate:
        """Enforce that each step carries exactly the fields its type needs."""
        if self.step_type is WorkflowStepType.COMMAND:
            if not self.command_type:
                raise ValueError("command_type is required for a COMMAND step")
        elif self.step_type is WorkflowStepType.SLEEP:
            if self.sleep_seconds is None:
                raise ValueError("sleep_seconds is required for a SLEEP step")
        elif self.step_type is WorkflowStepType.GROUP:
            if self.group_mode is None:
                raise ValueError("group_mode is required for a GROUP step")
            if not self.children:
                raise ValueError("a GROUP step must have at least one child step")
            if self.group_mode is WorkflowGroupMode.PARALLEL and len(self.children) < 2:
                raise ValueError("a PARALLEL group must have at least two child steps")
        return self


class WorkflowCreate(BaseModel):
    """Input for defining a new workflow, or replacing an existing one wholesale."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    steps: list[WorkflowStepCreate] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def validate_has_steps(cls, value: list[WorkflowStepCreate]) -> list[WorkflowStepCreate]:
        """A workflow with no steps would never do anything if run."""
        if not value:
            raise ValueError("a workflow must have at least one step")
        return value


class WorkflowUpdate(WorkflowCreate):
    """Same shape as create — a PUT always replaces the full definition."""
