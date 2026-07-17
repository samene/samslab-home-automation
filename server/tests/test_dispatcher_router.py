"""Tests for the read-only Command Dispatcher admin REST endpoints."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Environment, Settings
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.tokens import new_jti
from app.main import create_app

_JWT_SECRET = "a-sufficiently-long-test-signing-secret-value"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        SERVER_NAME="Dispatcher Router Test", ENVIRONMENT=Environment.TEST, JWT_SECRET=_JWT_SECRET
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def jwt_codec(settings: Settings) -> JWTCodec:
    return JWTCodec(
        secret=settings.jwt_secret.get_secret_value(),  # type: ignore[union-attr]
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        clock_skew_seconds=settings.jwt_clock_skew_seconds,
    )


def _admin_token(jwt_codec: JWTCodec) -> str:
    roles = ["Admin"]
    return jwt_codec.encode(
        subject=str(uuid4()),
        expires_in=timedelta(minutes=5),
        jti=new_jti(),
        claims={
            "principal_type": "USER",
            "role": roles,
            "permissions": sorted(permissions_for_roles(roles)),
        },
    )


def _viewer_token(jwt_codec: JWTCodec) -> str:
    roles = ["Viewer"]
    return jwt_codec.encode(
        subject=str(uuid4()),
        expires_in=timedelta(minutes=5),
        jti=new_jti(),
        claims={
            "principal_type": "USER",
            "role": roles,
            "permissions": sorted(permissions_for_roles(roles)),
        },
    )


@pytest.mark.parametrize(
    "path",
    ["/dispatcher/status", "/dispatcher/queue", "/dispatcher/running", "/dispatcher/statistics"],
)
def test_admin_endpoints_require_authentication(app: FastAPI, path: str) -> None:
    """Every dispatcher admin endpoint rejects an unauthenticated request."""
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/dispatcher/status", "/dispatcher/queue", "/dispatcher/running", "/dispatcher/statistics"],
)
def test_admin_endpoints_require_system_admin_permission(
    app: FastAPI, jwt_codec: JWTCodec, path: str
) -> None:
    """A user without system.admin cannot read dispatcher admin endpoints."""
    token = _viewer_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_status_reports_a_running_dispatcher(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """An admin sees the dispatcher's run state, since the app fixture has no database."""
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get("/dispatcher/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert "running" in body
    assert "queue_depth" in body
    assert "pending_ack_count" in body
    assert "running_count" in body
    assert "poll_interval_seconds" in body


def test_queue_is_empty_by_default(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """With no commands, the queue admin endpoint returns an empty list."""
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get("/dispatcher/queue", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_running_is_empty_by_default(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """With no in-flight commands, the running admin endpoint returns an empty list."""
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get("/dispatcher/running", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_statistics_reports_the_expected_counters(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """The statistics endpoint reports every documented counter field."""
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get(
            "/dispatcher/statistics", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    body = response.json()
    for field in (
        "commands_dispatched_total",
        "dispatch_failures_total",
        "dispatcher_retries_total",
        "dispatcher_timeouts_total",
        "queue_depth",
        "pending_ack_count",
        "running_count",
    ):
        assert field in body
