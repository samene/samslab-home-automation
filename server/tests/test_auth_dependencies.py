"""Tests for the reusable FastAPI auth dependencies (token resolution only)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.application.exceptions import UnauthorizedError
from app.config.settings import Settings
from app.domains.auth.dependencies import (
    CurrentDevice,
    CurrentPrincipal,
    CurrentUser,
    get_jwt_codec,
)
from app.domains.auth.jwt import JWTCodec

_JWT_CODEC = JWTCodec(
    secret="a-sufficiently-long-test-signing-secret-value",
    algorithm="HS256",
    issuer="samslab",
    audience="samslab-clients",
    clock_skew_seconds=5,
)


class _FakeContainer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def settings(self) -> Settings:
        return self._settings


class _FakeAppState:
    def __init__(self, container: _FakeContainer) -> None:
        self.container = container


class _FakeApp:
    def __init__(self, settings: Settings) -> None:
        self.state = _FakeAppState(_FakeContainer(settings))


class _FakeRequest:
    """A minimal stand-in for FastAPI's Request, exposing only what get_jwt_codec reads."""

    def __init__(self, settings: Settings) -> None:
        self.app = _FakeApp(settings)


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _user_token(**claim_overrides: object) -> str:
    claims: dict[str, object] = {
        "principal_type": "USER",
        "role": ["Admin"],
        "permissions": ["system.admin"],
    }
    claims.update(claim_overrides)
    return _JWT_CODEC.encode(
        subject=str(uuid4()), expires_in=timedelta(minutes=5), jti="jti-1", claims=claims
    )


def _device_token() -> str:
    device_id = uuid4()
    return _JWT_CODEC.encode(
        subject=str(device_id),
        expires_in=timedelta(minutes=5),
        jti="jti-2",
        claims={
            "principal_type": "DEVICE",
            "role": ["Agent"],
            "permissions": ["commands.execute"],
            "device_id": str(device_id),
        },
    )


def test_get_jwt_codec_raises_when_jwt_is_not_configured() -> None:
    """A missing JWT secret fails safely with a 503, not an unhandled error."""
    request = _FakeRequest(Settings(JWT_SECRET=None))
    with pytest.raises(HTTPException) as exc_info:
        get_jwt_codec(request)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 503


def test_get_jwt_codec_builds_a_working_codec_from_settings() -> None:
    """A configured JWT secret produces a codec that can decode its own tokens."""
    request = _FakeRequest(Settings(JWT_SECRET="a-configured-signing-secret-value"))
    codec = get_jwt_codec(request)  # type: ignore[arg-type]
    token = codec.encode(
        subject="x", expires_in=timedelta(minutes=1), jti="jti-1", claims={"principal_type": "USER"}
    )
    assert codec.decode(token)["sub"] == "x"


@pytest.mark.asyncio
async def test_current_principal_resolves_a_valid_token() -> None:
    """A well-formed, valid bearer token resolves to its Principal."""
    principal = await CurrentPrincipal(credentials=_bearer(_user_token()), jwt_codec=_JWT_CODEC)
    assert principal.principal_type.value == "USER"
    assert principal.roles == frozenset({"Admin"})


@pytest.mark.asyncio
async def test_current_principal_raises_unauthorized_without_credentials() -> None:
    """A missing Authorization header raises UnauthorizedError, not a 500."""
    with pytest.raises(UnauthorizedError):
        await CurrentPrincipal(credentials=None, jwt_codec=_JWT_CODEC)


@pytest.mark.asyncio
async def test_current_principal_translates_an_invalid_token() -> None:
    """An undecodable bearer token translates to the application's UnauthorizedError."""
    with pytest.raises(UnauthorizedError):
        await CurrentPrincipal(credentials=_bearer("not-a-real-token"), jwt_codec=_JWT_CODEC)


@pytest.mark.asyncio
async def test_current_principal_translates_an_expired_token() -> None:
    """An expired bearer token also translates to UnauthorizedError."""
    expired = _JWT_CODEC.encode(
        subject="x",
        expires_in=timedelta(seconds=-60),
        jti="jti-1",
        claims={"principal_type": "USER"},
    )
    with pytest.raises(UnauthorizedError):
        await CurrentPrincipal(credentials=_bearer(expired), jwt_codec=_JWT_CODEC)


@pytest.mark.asyncio
async def test_current_user_accepts_a_user_principal() -> None:
    """CurrentUser passes through a principal whose type is USER."""
    principal = await CurrentPrincipal(credentials=_bearer(_user_token()), jwt_codec=_JWT_CODEC)
    assert (await CurrentUser(principal=principal)) is principal


@pytest.mark.asyncio
async def test_current_user_rejects_a_device_principal() -> None:
    """CurrentUser refuses a principal whose type is DEVICE."""
    principal = await CurrentPrincipal(credentials=_bearer(_device_token()), jwt_codec=_JWT_CODEC)
    with pytest.raises(UnauthorizedError):
        await CurrentUser(principal=principal)


@pytest.mark.asyncio
async def test_current_device_accepts_a_device_principal() -> None:
    """CurrentDevice passes through a principal whose type is DEVICE."""
    principal = await CurrentPrincipal(credentials=_bearer(_device_token()), jwt_codec=_JWT_CODEC)
    assert (await CurrentDevice(principal=principal)) is principal


@pytest.mark.asyncio
async def test_current_device_rejects_a_user_principal() -> None:
    """CurrentDevice refuses a principal whose type is USER."""
    principal = await CurrentPrincipal(credentials=_bearer(_user_token()), jwt_codec=_JWT_CODEC)
    with pytest.raises(UnauthorizedError):
        await CurrentDevice(principal=principal)
