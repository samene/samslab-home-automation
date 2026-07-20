"""Shared FastAPI dependency providers usable across domain delivery adapters."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.application.events.bus import EventBus
from app.core.database import Database
from app.notifications.service import NotificationService


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


def get_notification_service(request: Request) -> NotificationService:
    """Resolve the per-application Notification Service from the DI container.

    Unlike ``get_database``, a missing database never raises here — sending
    a notification (and the Settings page's status/test actions) works fine
    with no DB configured; only the delivery-history log becomes a no-op.
    """
    notification_service: NotificationService = request.app.state.container.notification_service()
    return notification_service
