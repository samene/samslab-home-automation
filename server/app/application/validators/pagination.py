"""Centralized, bounded pagination parameters shared by every list use case.

Controllers pass raw ``offset``/``limit`` query values through unvalidated;
bounds are enforced exactly once, here, instead of being redeclared with
``Query(ge=..., le=...)`` in every domain's controller.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.application.exceptions import ApplicationValidationError


class PaginationParams(BaseModel):
    """A validated, bounded ``offset``/``limit`` pair."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @classmethod
    def create(cls, *, offset: int, limit: int) -> PaginationParams:
        """Validate raw ``offset``/``limit`` values, raising the application's own error."""
        try:
            return cls(offset=offset, limit=limit)
        except PydanticValidationError as error:
            raise ApplicationValidationError(str(error)) from error
