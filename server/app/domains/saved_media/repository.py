"""SQLAlchemy repository implementing all Saved Media persistence operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.saved_media.models import MediaType, SavedMedia


class SavedMediaRepository:
    """Persist and query saved media without leaking SQLAlchemy into application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    async def create(self, media: SavedMedia) -> SavedMedia:
        """Stage a new saved media row for commit by the application service."""
        self._session.add(media)
        await self._session.flush()
        await self._session.refresh(media)
        return media

    async def find_by_id(self, media_id: UUID) -> SavedMedia | None:
        """Find one saved media row by UUID."""
        result = await self._session.execute(select(SavedMedia).where(SavedMedia.id == media_id))
        return result.scalar_one_or_none()

    async def find_all(
        self,
        *,
        device_id: UUID | None,
        media_type: MediaType | None,
        captured_after: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[SavedMedia], int]:
        """List saved media newest-first, optionally scoped by device/type/time window."""
        filters: list[ColumnElement[bool]] = []
        if device_id is not None:
            filters.append(SavedMedia.device_id == device_id)
        if media_type is not None:
            filters.append(SavedMedia.media_type == media_type)
        if captured_after is not None:
            filters.append(SavedMedia.captured_at >= captured_after)
        count = await self._session.scalar(select(func.count(SavedMedia.id)).where(*filters))
        result = await self._session.execute(
            select(SavedMedia)
            .where(*filters)
            .order_by(SavedMedia.captured_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), count or 0

    async def find_by_workflow_id(self, workflow_id: UUID) -> list[SavedMedia]:
        """Return every saved media row a given workflow's runs have ever produced."""
        result = await self._session.execute(
            select(SavedMedia).where(SavedMedia.workflow_id == workflow_id)
        )
        return list(result.scalars())

    async def find_by_workflow_run_id(self, workflow_run_id: UUID) -> list[SavedMedia]:
        """Return every saved media row one specific workflow run produced, oldest first.

        Oldest-first (rather than the newest-first convention ``find_all``
        uses for a browsing list) matters to the Notification Framework's
        "first one if multiple" tie-break for which thumbnail to attach —
        see ``app.application.services.workflow_service``.
        """
        result = await self._session.execute(
            select(SavedMedia)
            .where(SavedMedia.workflow_run_id == workflow_run_id)
            .order_by(SavedMedia.created_at)
        )
        return list(result.scalars())

    async def delete(self, media: SavedMedia) -> None:
        """Hard-delete a saved media row — a real S3 object is being removed, not archived."""
        await self._session.delete(media)
        await self._session.flush()
