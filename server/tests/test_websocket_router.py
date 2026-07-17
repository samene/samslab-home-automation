"""Tests for the admin REST endpoints and /metrics exposed alongside the WS route."""

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
from app.websocket.session import ConnectionState, Session

_JWT_SECRET = "a-sufficiently-long-test-signing-secret-value"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        SERVER_NAME="WS Router Test",
        ENVIRONMENT=Environment.TEST,
        JWT_SECRET=_JWT_SECRET,
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


def _fake_session(device_id: object) -> Session:
    from datetime import UTC, datetime

    from app.domains.auth.schemas import Principal, PrincipalType

    class _FakeConnection:
        pending_acks: dict[object, object] = {}

        async def close(self, *, code: int = 1000, reason: str = "") -> None:
            return None

    now = datetime.now(UTC)
    return Session(
        device_id=device_id,  # type: ignore[arg-type]
        connection_id=uuid4(),
        connected_at=now,
        last_seen=now,
        protocol_version=1,
        authenticated_principal=Principal(
            principal_type=PrincipalType.DEVICE, subject_id="dev", device_id=uuid4()
        ),
        connection=_FakeConnection(),  # type: ignore[arg-type]
        connection_state=ConnectionState.OPEN,
    )


def test_list_sessions_requires_authentication(app: FastAPI) -> None:
    """The admin sessions listing is not publicly accessible."""
    with TestClient(app) as client:
        response = client.get("/ws/sessions")
    assert response.status_code == 401


def test_list_sessions_requires_the_system_admin_permission(
    app: FastAPI, jwt_codec: JWTCodec
) -> None:
    """A user without system.admin cannot list sessions."""
    token = _viewer_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get("/ws/sessions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_list_sessions_returns_every_tracked_session(app: FastAPI, jwt_codec: JWTCodec) -> None:
    """An admin sees a summary for every currently registered session."""
    session_manager = app.state.container.session_manager()
    device_id = uuid4()
    session_manager._sessions[device_id] = _fake_session(device_id)  # noqa: SLF001
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get("/ws/sessions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert any(item["device_id"] == str(device_id) for item in body)


def test_get_session_returns_404_for_an_unconnected_device(
    app: FastAPI, jwt_codec: JWTCodec
) -> None:
    """Looking up a device with no active session returns a 404 problem response."""
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get(
            f"/ws/sessions/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_get_session_returns_the_summary_for_a_connected_device(
    app: FastAPI, jwt_codec: JWTCodec
) -> None:
    """Looking up a connected device's session returns its summary."""
    session_manager = app.state.container.session_manager()
    device_id = uuid4()
    session_manager._sessions[device_id] = _fake_session(device_id)  # noqa: SLF001
    token = _admin_token(jwt_codec)
    with TestClient(app) as client:
        response = client.get(
            f"/ws/sessions/{device_id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert response.json()["device_id"] == str(device_id)


def test_metrics_endpoint_exposes_prometheus_format(app: FastAPI) -> None:
    """The /metrics endpoint is unauthenticated and returns Prometheus text exposition format."""
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert b"connected_devices" in response.content
    assert response.headers["content-type"].startswith("text/plain")
