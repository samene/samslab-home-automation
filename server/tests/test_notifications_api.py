"""REST tests for the Notification Framework's Settings-page surface.

Deliberately never configures real Telegram credentials — ``TelegramProvider``
short-circuits before any network call when it isn't configured, which is
exactly what keeps this test suite offline (see
``test_notifications_telegram_provider.py`` for the mocked-transport tests
that exercise the real HTTP path).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.main import create_app
from app.notifications.models import NotificationLog


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'notifications_api.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def _app_for(database: Database, **settings_overrides: object) -> FastAPI:
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            **settings_overrides,  # type: ignore[arg-type]
        )
    )
    app.state.container.database.override(database)
    return app


async def test_get_status_reports_telegram_as_unconfigured_by_default(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/notifications/status")

    assert response.status_code == 200
    body = response.json()
    assert body["providers"] == [
        {
            "provider": "telegram",
            "enabled": False,
            "configured": False,
            "last_attempt_at": None,
            "last_success": None,
            "last_error": None,
        }
    ]


async def test_post_test_notification_returns_200_even_when_disabled(database: Database) -> None:
    """Testing a notification and learning it can't send is a result, not a server error."""
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/notifications/test")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["provider"] == "telegram"
    assert body[0]["success"] is False
    assert "disabled" in body[0]["error_message"]


async def test_post_test_notification_reports_not_configured_when_enabled_without_credentials(
    database: Database,
) -> None:
    app = _app_for(database, TELEGRAM_ENABLED=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/notifications/test")

    body = response.json()
    assert body[0]["success"] is False
    assert "not configured" in body[0]["error_message"]


async def test_post_test_notification_records_a_notification_log_row(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/notifications/test")

    async with database.session_factory() as session:
        rows = (await session.execute(select(NotificationLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "TEST"
    assert rows[0].success is False


async def test_get_status_reflects_a_prior_test_notification(database: Database) -> None:
    app = _app_for(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/notifications/test")
        response = await client.get("/notifications/status")

    body = response.json()
    assert body["providers"][0]["last_attempt_at"] is not None
    assert body["providers"][0]["last_success"] is False
