"""Reusable field-level validation rules shared by the Command domain's schemas."""

from __future__ import annotations

import re
from datetime import UTC, datetime

COMMAND_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def validate_command_type(value: str) -> str:
    """Require a lowercase, dot-namespaced identifier such as ``pump.start``.

    The server never hardcodes hardware-specific command types; any future
    plugin can introduce new dot-namespaced strings without a server change.
    """
    if not COMMAND_TYPE_PATTERN.fullmatch(value):
        raise ValueError(
            "command_type must be lowercase, dot-namespaced identifiers (e.g. 'pump.start')"
        )
    return value


def validate_expiration_window(scheduled_at: datetime | None, expires_at: datetime | None) -> None:
    """Reject an expiration that could never leave a command time to run."""
    if expires_at is None:
        return
    if scheduled_at is not None:
        if expires_at <= scheduled_at:
            raise ValueError("expires_at must be after scheduled_at")
        return
    if expires_at <= datetime.now(UTC):
        raise ValueError("expires_at must be in the future")
