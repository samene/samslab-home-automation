"""Abstraction over a durable audit trail; no concrete implementation exists yet."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AuditRecorder(ABC):
    """A future durable record of administrative and security-relevant actions."""

    @abstractmethod
    async def record(
        self, *, actor: str | None, action: str, context: dict[str, Any] | None = None
    ) -> None:
        """Record that ``actor`` performed ``action``, with optional structured ``context``."""
