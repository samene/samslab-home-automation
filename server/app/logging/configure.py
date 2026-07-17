"""Structlog configuration for development console and production JSON output."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.config.settings import Environment, Settings


def _add_required_fields(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Ensure every event has the standard operational fields."""
    event_dict.setdefault("request_id", None)
    event_dict.setdefault("correlation_id", None)
    event_dict.setdefault("logger", event_dict.get("logger_name", "sams_lab"))
    event_dict.setdefault("message", event_dict.get("event", ""))
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure process logging once at application lifespan startup.

    Structlog's processor registry is process-wide by library design. Runtime settings
    and logger instances remain application-owned and are passed through the factory.
    """
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level, logging.INFO),
        stream=sys.stdout,
        force=True,
    )
    renderer: structlog.types.Processor
    if settings.environment is Environment.DEVELOPMENT:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.stdlib.add_logger_name,
            _add_required_fields,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
