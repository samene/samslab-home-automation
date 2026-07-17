"""Abstraction over binary object storage; no concrete implementation exists yet.

Intended for future media (camera captures, uploaded files) once a domain
needs it — see ``docs/architecture/DEPLOYMENT.md`` for the planned S3-compatible
backend. No domain currently stores binary objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStorage(ABC):
    """A content-addressable store for binary objects, independent of the backend."""

    @abstractmethod
    async def put(self, key: str, data: bytes) -> str:
        """Store ``data`` under ``key`` and return a retrievable reference."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve the bytes previously stored under ``key``."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object stored under ``key``, if any."""
