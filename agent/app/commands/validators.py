"""Reusable field-validation functions, called from a handler's ``validate()``.

Pulled into their own file rather than inlined per-handler once there's more
than a line or two of validation logic to share — same rationale as the cloud
server's own ``commands/validators.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from app.commands.exceptions import CommandValidationError

#: Mirrors the cloud server's own command_type shape: lowercase, dot-namespaced.
COMMAND_TYPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def validate_command_type_format(command_type: str) -> None:
    """Raise ``CommandValidationError`` unless ``command_type`` is lowercase and dot-namespaced."""
    if not COMMAND_TYPE_PATTERN.match(command_type):
        raise CommandValidationError(f"Malformed command_type: {command_type!r}")


def require_keys(arguments: Mapping[str, Any], *keys: str) -> None:
    """Raise ``CommandValidationError`` unless every one of ``keys`` is present in ``arguments``."""
    missing = [key for key in keys if key not in arguments]
    if missing:
        raise CommandValidationError(f"Missing required argument(s): {', '.join(missing)}")


def require_type(arguments: Mapping[str, Any], key: str, expected_type: type) -> None:
    """Raise ``CommandValidationError`` unless ``arguments[key]`` is an instance of ``expected_type``.

    Assumes the key's presence was already checked (e.g. via ``require_keys``);
    a missing key raises ``KeyError`` intentionally rather than being silently
    treated as a validation failure.
    """
    value = arguments[key]
    if not isinstance(value, expected_type):
        raise CommandValidationError(
            f"Argument {key!r} must be of type {expected_type.__name__}, got {type(value).__name__}"
        )
