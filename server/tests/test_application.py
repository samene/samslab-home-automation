"""Tests for application factory isolation and lifespan lifecycle."""

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.application.exceptions import ApplicationError
from app.config.settings import Settings
from app.main import application_exception_handler, create_app


def test_application_factory_creates_isolated_containers(settings: Settings) -> None:
    """Each factory invocation owns a distinct dependency container."""
    first = create_app(settings)
    second = create_app(settings)

    assert first is not second
    assert first.state.container is not second.state.container


@pytest.mark.asyncio
async def test_application_starts_and_stops_cleanly(app: FastAPI) -> None:
    """The lifespan starts and stops cleanly while endpoints remain available."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/live")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_application_exception_handler_defaults_unmapped_errors_to_400() -> None:
    """An ApplicationError outside the three known categories still yields a safe problem.

    REST only ever handles ``ApplicationError`` and its subclasses — never a
    domain's own exception types — so this is the one place that mapping is
    tested directly, independent of any specific domain.
    """
    request = Request({"type": "http", "path": "/", "headers": []})
    response = await application_exception_handler(request, ApplicationError("unmapped"))
    assert response.status_code == 400
