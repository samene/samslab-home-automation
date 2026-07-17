"""Tests for /ready folding in whether a started Command Dispatcher is still running.

Uses the app's ``lifespan`` context manager directly (not ``TestClient``), so
everything runs on the single event loop pytest-asyncio already manages —
consistent with the rest of this session's WebSocket/dispatcher tests, and
necessary here since we need to call the async ``dispatcher.stop()`` from the
test body on the *same* loop the dispatcher's own tasks were created on.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.config.settings import Environment, Settings
from app.main import create_app, lifespan


@pytest.mark.asyncio
async def test_ready_is_ok_while_the_dispatcher_is_running(tmp_path: Path) -> None:
    """With a database configured, the dispatcher starts and /ready reports ok."""
    settings = Settings(
        SERVER_NAME="Health Dispatcher Test",
        ENVIRONMENT=Environment.TEST,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'ready.db'}",
    )
    app = create_app(settings)
    await app.state.container.database().create_schema_for_testing()

    async with lifespan(app):
        assert app.state.container.dispatcher().is_running is True
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_becomes_unhealthy_after_the_dispatcher_stops(tmp_path: Path) -> None:
    """A dispatcher that was running and then stopped flips /ready to unhealthy."""
    settings = Settings(
        SERVER_NAME="Health Dispatcher Test",
        ENVIRONMENT=Environment.TEST,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'ready.db'}",
    )
    app = create_app(settings)
    await app.state.container.database().create_schema_for_testing()

    async with lifespan(app):
        dispatcher = app.state.container.dispatcher()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            healthy_response = await client.get("/ready")
            assert healthy_response.status_code == 200

            await dispatcher.stop()  # simulate the worker task having stopped/crashed

            unhealthy_response = await client.get("/ready")
            assert unhealthy_response.status_code == 503
            assert unhealthy_response.json() == {"status": "unhealthy"}
