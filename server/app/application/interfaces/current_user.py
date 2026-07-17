"""Abstraction over the caller's identity; no concrete implementation exists yet.

There is no authentication in this phase. This interface exists so that once
authentication is introduced, application services can depend on it rather
than on a specific auth mechanism.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CurrentUserProvider(ABC):
    """A future request-scoped accessor for the authenticated caller's identity."""

    @abstractmethod
    def get_user_id(self) -> str | None:
        """Return the current caller's identifier, or ``None`` if unauthenticated."""
