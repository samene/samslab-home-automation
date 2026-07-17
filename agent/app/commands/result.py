"""The command runtime's own structured outcome — richer than the wire's ``CommandResultPayload``.

``CommandDispatcher`` maps a ``CommandResult`` down to the existing
``CommandResultPayload`` (``success``/``result``/``error_message`` only) when
it actually sends ``COMMAND_RESULT``; the extra fields here (status, duration,
exit code, stack trace) are for local logging/metrics/observability and never
need the wire schema itself to change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

#: Exit-code convention borrowed from the shell: 0 success, 1 a generic
#: failure, 124 the ``timeout(1)`` convention, 130 the 128+SIGINT convention
#: for a cancelled operation.
EXIT_CODE_SUCCESS: Final[int] = 0
EXIT_CODE_FAILURE: Final[int] = 1
EXIT_CODE_TIMEOUT: Final[int] = 124
EXIT_CODE_CANCELLED: Final[int] = 130


class CommandResultStatus(StrEnum):
    """A command's terminal outcome."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class CommandResult:
    """The full outcome of one command execution."""

    command_id: UUID
    status: CommandResultStatus
    duration_seconds: float
    result: Mapping[str, Any] | None = None
    error_message: str | None = None
    stack_trace: str | None = None
    exit_code: int = EXIT_CODE_SUCCESS
