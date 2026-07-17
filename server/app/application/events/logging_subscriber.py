"""A structured-log subscriber wired to every domain event at startup.

This is observability, not one of the "future" features (notification, audit,
metrics, automation) called out as not-yet-implemented — it only logs. It
also doubles as the reference example for subscribing a handler to the bus.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import structlog

from app.application.events.bus import EventBus
from app.application.events.domain_events import (
    CommandCompleted,
    CommandCreated,
    CommandFailed,
    DeviceHeartbeat,
    DeviceRegistered,
    UserLoggedIn,
)

_logger = structlog.get_logger("domain.events")


def log_domain_event(event: Any) -> None:
    """Log any dataclass domain event as one structured entry."""
    _logger.info(type(event).__name__, **asdict(event))


def register_logging_subscriber(event_bus: EventBus) -> None:
    """Subscribe the structured-log handler to every known domain event type."""
    for event_type in (
        DeviceRegistered,
        DeviceHeartbeat,
        CommandCreated,
        CommandCompleted,
        CommandFailed,
        UserLoggedIn,
    ):
        event_bus.subscribe(event_type, log_domain_event)
