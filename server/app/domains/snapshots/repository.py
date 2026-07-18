"""SQLAlchemy repository implementing all Snapshots persistence operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.snapshots.models import Snapshot


class SnapshotRepository:
    """Persist and query snapshots without leaking SQLAlchemy into application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    async def create(self, snapshot: Snapshot) -> Snapshot:
        """Stage a new snapshot for commit by the application service."""
        self._session.add(snapshot)
        await self._session.flush()
        await self._session.refresh(snapshot)
        return snapshot

    async def find_by_id(self, snapshot_id: UUID) -> Snapshot | None:
        """Find one snapshot by UUID."""
        result = await self._session.execute(select(Snapshot).where(Snapshot.id == snapshot_id))
        return result.scalar_one_or_none()

    async def find_all(
        self, *, device_id: UUID | None, offset: int, limit: int
    ) -> tuple[list[Snapshot], int]:
        """List snapshots newest-first, optionally scoped to one device."""
        filters = [] if device_id is None else [Snapshot.device_id == device_id]
        count = await self._session.scalar(select(func.count(Snapshot.id)).where(*filters))
        result = await self._session.execute(
            select(Snapshot)
            .where(*filters)
            .order_by(Snapshot.captured_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), count or 0

    async def delete(self, snapshot: Snapshot) -> None:
        """Hard-delete a snapshot row — a real S3 object is being removed, not archived."""
        await self._session.delete(snapshot)
        await self._session.flush()
