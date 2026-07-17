"""Transaction-boundary abstraction; no concrete implementation exists yet.

Today, each domain's FastAPI dependency (e.g. ``get_device_service``) opens
its own session and commits/rolls back around one request. A ``UnitOfWork``
is the seam a future multi-repository, multi-domain transaction would use
instead, without changing any application service's call signature.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class UnitOfWork(ABC):
    """An atomic boundary spanning one or more repository operations."""

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Begin the unit of work."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Roll back on an unhandled exception; otherwise leave the caller to commit."""

    @abstractmethod
    async def commit(self) -> None:
        """Durably persist every change made within this unit of work."""

    @abstractmethod
    async def rollback(self) -> None:
        """Discard every change made within this unit of work."""
