"""Abstraction over identifier generation; no concrete implementation exists yet."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class IdGenerator(ABC):
    """A source of new identifiers, so future non-UUID or deterministic schemes fit here."""

    @abstractmethod
    def new_id(self) -> UUID:
        """Return a new, unique identifier."""
