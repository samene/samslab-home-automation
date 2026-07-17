"""Context-variable helpers for propagating request and correlation identifiers."""

from __future__ import annotations

from collections.abc import Mapping

import structlog


def bind_request_context(*, request_id: str, correlation_id: str) -> None:
    """Bind identifiers to the current async context for all subsequent log events."""
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        correlation_id=correlation_id,
    )


def clear_request_context() -> None:
    """Clear request-scoped identifiers after a request completes."""
    structlog.contextvars.clear_contextvars()


def get_request_context() -> Mapping[str, str]:
    """Return a copy of currently bound structured-log context."""
    return structlog.contextvars.get_contextvars()
