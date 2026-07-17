"""Abstraction over wall-clock time; no concrete implementation exists yet."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """A source of the current time, so services depending on it stay testable."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time."""
