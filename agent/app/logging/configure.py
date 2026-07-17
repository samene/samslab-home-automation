"""structlog configuration: always JSON, since the agent's stdout is captured by journald."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.config.settings import AgentSettings


def _add_required_fields(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Ensure every event carries the standard agent correlation fields."""
    event_dict.setdefault("device_id", None)
    event_dict.setdefault("connection_id", None)
    event_dict.setdefault("message_id", None)
    event_dict.setdefault("correlation_id", None)
    event_dict.setdefault("trace_id", None)
    event_dict.setdefault("logger", event_dict.get("logger_name", "samslab_agent"))
    event_dict.setdefault("message", event_dict.get("event", ""))
    return event_dict


def configure_logging(settings: AgentSettings) -> None:
    """Configure process logging once at agent startup.

    Structlog's processor registry is process-wide by library design, so this
    is meant to be called exactly once, before any other module obtains a
    logger via ``structlog.get_logger``.
    """
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level, logging.INFO),
        stream=sys.stdout,
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.stdlib.add_logger_name,
            _add_required_fields,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def bind_context(
    *,
    device_id: str | None = None,
    connection_id: str | None = None,
    message_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Bind whichever identifiers are known onto every subsequent log event.

    Only the fields explicitly passed are bound — callers rebind a narrower
    context (e.g. a new ``message_id`` per message) without clobbering
    identifiers set by an outer scope (e.g. ``connection_id`` for the session).
    """
    fields = {
        "device_id": device_id,
        "connection_id": connection_id,
        "message_id": message_id,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
    }
    structlog.contextvars.bind_contextvars(
        **{key: value for key, value in fields.items() if value is not None}
    )


def clear_context() -> None:
    """Clear all bound log context, e.g. after a connection closes."""
    structlog.contextvars.clear_contextvars()
