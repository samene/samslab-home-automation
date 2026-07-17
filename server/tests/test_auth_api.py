"""API-level tests for the Auth domain's REST endpoints."""

from __future__ import annotations

import base64
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.models import Role, User
from app.domains.auth.passwords import hash_password
from app.domains.auth.repository import AuthRepository
from app.domains.auth.service import AuthService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService
from app.main import create_app


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'auth_api.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def build_app(database: Database) -> FastAPI:
    """Build a real app wired to the given database, with JWT configured."""
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            JWT_SECRET="a-sufficiently-long-test-signing-secret-value",
        )
    )
    app.state.container.database.override(database)
    return app


async def seed_user(
    database: Database, *, username: str = "sam", password: str = "s3cret-pw", enabled: bool = True
) -> None:
    """Register one Admin user, committed and visible to subsequent requests."""
    async with database.session_factory() as session:
        repository = AuthRepository(session)
        role = Role(name="Admin", description="test role")
        session.add(role)
        await session.flush()
        user = await repository.create_user(
            User(
                username=username,
                email=f"{username}@example.com",
                password_hash=hash_password(password),
                enabled=enabled,
            )
        )
        await repository.assign_role(user, role)
        await session.commit()


@pytest.mark.asyncio
async def test_login_returns_a_token_pair(database: Database) -> None:
    """A correct login returns access_token/refresh_token/token_type/expires_in."""
    await seed_user(database)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/login", json={"username": "sam", "password": "s3cret-pw"}
        )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_with_rfc7807_401(database: Database) -> None:
    """A wrong password yields a 401 RFC 7807 problem, not a raw error."""
    await seed_user(database)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/auth/login", json={"username": "sam", "password": "wrong"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "InvalidCredentialsError"


@pytest.mark.asyncio
async def test_login_rejects_a_disabled_account(database: Database) -> None:
    """A disabled account's login attempt yields a 401 with a distinct problem type."""
    await seed_user(database, enabled=False)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/login", json={"username": "sam", "password": "s3cret-pw"}
        )
    assert response.status_code == 401
    assert response.json()["title"] == "DisabledAccountError"


@pytest.mark.asyncio
async def test_login_validates_missing_fields(database: Database) -> None:
    """A malformed login body (missing password) is a 422 request-validation failure."""
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/auth/login", json={"username": "sam"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_refresh_and_logout_round_trip(database: Database) -> None:
    """Refresh returns a new pair; logout revokes it; a further refresh then fails."""
    await seed_user(database)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/auth/login", json={"username": "sam", "password": "s3cret-pw"})
        refresh_token = login.json()["refresh_token"]

        refreshed = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 200
        new_refresh_token = refreshed.json()["refresh_token"]
        assert new_refresh_token != refresh_token

        stale = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert stale.status_code == 401

        logout = await client.post("/auth/logout", json={"refresh_token": new_refresh_token})
        assert logout.status_code == 204

        after_logout = await client.post("/auth/refresh", json={"refresh_token": new_refresh_token})
        assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_an_unknown_token_is_still_a_204(database: Database) -> None:
    """Logging out with a token that was never issued is treated as already logged out."""
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/auth/logout", json={"refresh_token": "never-issued"})
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_me_returns_the_authenticated_users_profile(database: Database) -> None:
    """GET /auth/me returns the caller's own profile, including resolved roles."""
    await seed_user(database)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/auth/login", json={"username": "sam", "password": "s3cret-pw"})
        access_token = login.json()["access_token"]

        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "sam"
    assert body["roles"] == ["Admin"]
    assert "password_hash" not in body


@pytest.mark.asyncio
async def test_me_requires_authentication(database: Database) -> None:
    """GET /auth/me without a bearer token is a 401 with a WWW-Authenticate header."""
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_me_rejects_a_device_token() -> None:
    """A device-typed token cannot use the user-only /auth/me endpoint."""
    codec = JWTCodec(
        secret="a-sufficiently-long-test-signing-secret-value",
        algorithm="HS256",
        issuer="samslab",
        audience="samslab-clients",
        clock_skew_seconds=5,
    )
    device_token = codec.encode(
        subject="device-1",
        expires_in=timedelta(minutes=5),
        jti="jti-1",
        claims={"principal_type": "DEVICE", "role": ["Agent"], "permissions": []},
    )
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            JWT_SECRET="a-sufficiently-long-test-signing-secret-value",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/me", headers={"Authorization": f"Bearer {device_token}"})
    assert response.status_code == 401


async def _seed_device_credential(database: Database) -> tuple[str, str]:
    """Register a device and issue it a credential; return (client_id, private_key_b64)."""
    async with database.session_factory() as session:
        device = await DeviceService(DeviceRepository(session)).register_device(
            DeviceCreate.model_validate(
                {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
            )
        )
        jwt_codec = JWTCodec(
            secret="a-sufficiently-long-test-signing-secret-value",
            algorithm="HS256",
            issuer="samslab",
            audience="samslab-clients",
            clock_skew_seconds=5,
        )
        auth = AuthService(
            AuthRepository(session),
            jwt_codec,
            access_token_ttl=timedelta(minutes=15),
            refresh_token_ttl=timedelta(days=14),
        )
        issued = await auth.issue_device_credential(device.id)
        await session.commit()
        return issued.client_id, issued.private_key_b64


def _sign_assertion(client_id: str, private_key_b64: str, *, ttl_seconds: int = 60) -> str:
    private_key = serialization.load_pem_private_key(
        base64.b64decode(private_key_b64), password=None
    )
    assert isinstance(private_key, rsa.RSAPrivateKey)
    now = int(time.time())
    return pyjwt.encode(
        {"sub": client_id, "iat": now, "exp": now + ttl_seconds}, private_key, algorithm="RS256"
    )


@pytest.mark.asyncio
async def test_device_token_round_trip(database: Database) -> None:
    """A device can exchange a freshly signed assertion for an access token, repeatedly."""
    client_id, private_key_b64 = await _seed_device_credential(database)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/auth/device/token",
            json={"client_id": client_id, "assertion": _sign_assertion(client_id, private_key_b64)},
        )
        assert first.status_code == 200
        body = first.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

        # A device can mint as many fresh tokens as it needs from the same permanent key —
        # this is exactly what fixes the "expired token, no way to reconnect" problem.
        second = await client.post(
            "/auth/device/token",
            json={"client_id": client_id, "assertion": _sign_assertion(client_id, private_key_b64)},
        )
        assert second.status_code == 200
        assert second.json()["access_token"] != body["access_token"]


@pytest.mark.asyncio
async def test_device_token_rejects_an_invalid_assertion(database: Database) -> None:
    """A malformed/unsigned assertion is rejected as invalid credentials, not a 500."""
    client_id, _ = await _seed_device_credential(database)
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/device/token", json={"client_id": client_id, "assertion": "not-a-jwt"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_device_token_rejects_an_unknown_client_id(database: Database) -> None:
    app = build_app(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/device/token", json={"client_id": "unknown", "assertion": "anything"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_returns_503_without_configured_database() -> None:
    """Auth endpoints needing persistence fail safely when no database is configured."""
    app = create_app(
        Settings(
            ENVIRONMENT=Environment.TEST,
            JWT_SECRET="a-sufficiently-long-test-signing-secret-value",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/auth/login", json={"username": "sam", "password": "x"})
    assert response.status_code == 503
