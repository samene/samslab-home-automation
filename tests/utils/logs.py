"""Capture and query the real server's structured JSON logs for assertions.

``configure_logging()`` (called from the app's own lifespan) renders every log
event as one JSON line to ``sys.stdout`` outside development — this captures
that stream for the duration of a ``with`` block so a test can assert on
``correlation_id``/``trace_id``/``command_id``/``device_id``/``connection_id``
without needing a real log aggregator.
"""

from __future__ import annotations

import io
import json
import sys
from typing import Any


class LogCapture:
    """Redirects ``sys.stdout`` to an in-memory buffer while active.

    Must be entered *before* the server harness starts, since
    ``configure_logging()`` binds ``logging.basicConfig(stream=sys.stdout)``
    once at startup, capturing whatever ``sys.stdout`` is at that moment.
    """

    def __init__(self) -> None:
        self._buffer = io.StringIO()
        self._real_stdout: Any = None

    def __enter__(self) -> LogCapture:
        self._real_stdout = sys.stdout
        sys.stdout = self._buffer
        return self

    def __exit__(self, *exc_info: object) -> None:
        sys.stdout = self._real_stdout

    def events(self) -> list[dict[str, Any]]:
        """Every captured line that parses as one JSON log event, in order."""
        events: list[dict[str, Any]] = []
        for line in self._buffer.getvalue().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
        return events

    def events_matching(self, **fields: Any) -> list[dict[str, Any]]:
        """Captured events whose fields match every given key/value exactly."""
        return [
            event
            for event in self.events()
            if all(event.get(key) == value for key, value in fields.items())
        ]
