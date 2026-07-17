"""Shared FastAPI dependency providers usable across domain delivery adapters."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.application.events.bus import EventBus
from app.core.database import Database


def get_database(request: Request) -> Database:
    """Resolve the application-owned database from the per-app DI container."""
    database: Database | None = request.app.state.container.database()
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return database


def get_event_bus(request: Request) -> EventBus:
    """Resolve the per-application, shared event bus from the DI container."""
    event_bus: EventBus = request.app.state.container.event_bus()
    return event_bus
