"""Application-owned async SQLAlchemy infrastructure with no domain query logic."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative metadata base for every domain's persistence models.

    Centralized so Alembic and test schema creation see one combined metadata
    registry regardless of which domain modules happen to import first.
    """


class Database:
    """Own an async engine and session factory for one application instance."""

    def __init__(self, database_url: str) -> None:
        """Create database infrastructure without opening a connection eagerly."""
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def dispose(self) -> None:
        """Release pool resources during application shutdown."""
        await self._engine.dispose()

    async def create_schema_for_testing(self) -> None:
        """Create metadata for isolated tests; production schema uses Alembic only.

        Relies on the caller having already imported every domain's ``models``
        module, which registers that domain's tables onto the shared ``Base``.
        """
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
