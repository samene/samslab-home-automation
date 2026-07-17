"""The closed set of immutable lifecycle events a command can emit."""

from __future__ import annotations

from enum import StrEnum


class CommandEventType(StrEnum):
    """One audit-trail event type per state-machine transition the service performs."""

    COMMAND_CREATED = "COMMAND_CREATED"
    COMMAND_DISPATCHED = "COMMAND_DISPATCHED"
    COMMAND_STARTED = "COMMAND_STARTED"
    COMMAND_COMPLETED = "COMMAND_COMPLETED"
    COMMAND_FAILED = "COMMAND_FAILED"
    COMMAND_CANCELLED = "COMMAND_CANCELLED"
    COMMAND_EXPIRED = "COMMAND_EXPIRED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    COMMAND_RETRY_SCHEDULED = "COMMAND_RETRY_SCHEDULED"
