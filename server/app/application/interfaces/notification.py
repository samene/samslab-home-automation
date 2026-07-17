"""Abstraction over outbound notifications; no concrete implementation exists yet."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NotificationSender(ABC):
    """A future outbound notification channel (email, push, chat, etc.)."""

    @abstractmethod
    async def send(
        self, *, recipient: str, message: str, context: dict[str, Any] | None = None
    ) -> None:
        """Send ``message`` to ``recipient`` with optional structured ``context``."""
