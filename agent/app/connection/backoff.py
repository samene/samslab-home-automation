"""Exponential backoff for reconnect delays."""

from __future__ import annotations


class ExponentialBackoff:
    """Doubling delay, capped at ``max_seconds``, reset after a successful connect."""

    def __init__(
        self, *, base_seconds: float, max_seconds: float = 300.0, multiplier: float = 2.0
    ) -> None:
        if base_seconds <= 0:
            raise ValueError("base_seconds must be positive")
        if max_seconds < base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if multiplier <= 1:
            raise ValueError("multiplier must be > 1")
        self._base = base_seconds
        self._max = max_seconds
        self._multiplier = multiplier
        self._attempt = 0

    def reset(self) -> None:
        """Return to the base delay, e.g. after a successful (re)connection."""
        self._attempt = 0

    def next_delay(self) -> float:
        """Return the next delay in seconds and advance the internal attempt counter."""
        delay = min(self._base * (self._multiplier**self._attempt), self._max)
        self._attempt += 1
        return delay
