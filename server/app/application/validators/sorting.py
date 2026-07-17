"""Centralized sort-field validation shared by every list use case."""

from __future__ import annotations

from app.application.exceptions import ApplicationValidationError


def validate_sort_field(sort: str, allowed_fields: frozenset[str]) -> str:
    """Validate a ``[-]field`` sort token against one use case's allowed field set."""
    key = sort[1:] if sort.startswith("-") else sort
    if key not in allowed_fields:
        raise ApplicationValidationError(
            f"Unsupported sort field '{key}'; expected one of {sorted(allowed_fields)}"
        )
    return sort
