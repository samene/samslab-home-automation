"""Tests for request context propagation and response observability headers."""

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_middleware_generates_request_and_correlation_ids(app: FastAPI) -> None:
    """Requests without identifiers receive generated, matching response identifiers."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_middleware_propagates_caller_identifiers(app: FastAPI) -> None:
    """Caller-provided IDs remain available to downstream logs and responses."""
    headers = {"X-Request-ID": "request-123", "X-Correlation-ID": "trace-456"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready", headers=headers)

    assert response.headers["x-request-id"] == "request-123"
    assert response.headers["x-correlation-id"] == "trace-456"
