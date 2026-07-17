"""Tests for dependency-free health delivery endpoints."""

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_root_describes_configured_service(app: FastAPI) -> None:
    """The root endpoint returns service identity and basic health status."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Sam's Lab Test Server"}


@pytest.mark.asyncio
async def test_health_endpoints_are_dependency_free(app: FastAPI) -> None:
    """Health, readiness, and liveness remain available before infrastructure exists."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/health", "/ready", "/live"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
