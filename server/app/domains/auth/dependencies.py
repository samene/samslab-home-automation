"""Reusable FastAPI dependencies for authentication and authorization.

Thin transport adapters only: every real decision (decoding a token,
checking a role or permission) is a pure, already-tested function or method
in ``jwt.py``/``service.py``. A future WebSocket handshake, gRPC interceptor,
or MQTT connector would call those directly instead of duplicating this
file — it would not reuse this file, because this file is FastAPI-specific
by design.

Token validation (``CurrentPrincipal``, ``RequireRole``, ``RequirePermission``)
never opens a database session: the token's claims are the full authorization
state. Only ``get_auth_application_service`` (used by the login/refresh/logout/me
routes themselves) opens one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.events.bus import EventBus
from app.application.exceptions import ForbiddenError, UnauthorizedError, translate_domain_error
from app.application.services.auth_service import AuthApplicationService
from app.config.settings import Settings
from app.core.database import Database
from app.dependencies import get_database, get_event_bus
from app.domains.auth.exceptions import AuthDomainError
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import Principal, PrincipalType
from app.domains.auth.service import AuthService, decode_principal
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.service import DeviceService

_bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_codec(request: Request) -> JWTCodec:
    """Build the request-scoped, session-free JWT codec from configured settings."""
    settings: Settings = request.app.state.container.settings()
    if settings.jwt_secret is None:
        raise HTTPException(status_code=503, detail="JWT is not configured")
    return JWTCodec(
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        clock_skew_seconds=settings.jwt_clock_skew_seconds,
    )


async def get_auth_application_service(
    request: Request,
    database: Database = Depends(get_database),
    event_bus: EventBus = Depends(get_event_bus),
    jwt_codec: JWTCodec = Depends(get_jwt_codec),
) -> AsyncIterator[AuthApplicationService]:
    """Inject a transaction-scoped application service and commit on success only."""
    settings: Settings = request.app.state.container.settings()
    async with database.session_factory() as session:
        try:
            yield AuthApplicationService(
                AuthService(
                    AuthRepository(session),
                    jwt_codec,
                    access_token_ttl=timedelta(seconds=settings.jwt_access_token_ttl_seconds),
                    refresh_token_ttl=timedelta(seconds=settings.jwt_refresh_token_ttl_seconds),
                ),
                DeviceService(DeviceRepository(session)),
                event_bus,
                access_token_ttl=timedelta(seconds=settings.jwt_access_token_ttl_seconds),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def CurrentPrincipal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    jwt_codec: JWTCodec = Depends(get_jwt_codec),
) -> Principal:
    """Resolve the bearer token on the request to its validated ``Principal``."""
    if credentials is None:
        raise UnauthorizedError("A bearer token is required")
    try:
        return decode_principal(jwt_codec, credentials.credentials)
    except AuthDomainError as error:
        raise translate_domain_error(error) from error


async def CurrentUser(principal: Principal = Depends(CurrentPrincipal)) -> Principal:
    """Require the resolved principal to be a human user."""
    if principal.principal_type is not PrincipalType.USER:
        raise UnauthorizedError("A user token is required")
    return principal


async def CurrentDevice(principal: Principal = Depends(CurrentPrincipal)) -> Principal:
    """Require the resolved principal to be a device (agent)."""
    if principal.principal_type is not PrincipalType.DEVICE:
        raise UnauthorizedError("A device token is required")
    return principal


def RequireRole(role: str) -> Callable[..., Awaitable[Principal]]:
    """Build a dependency requiring the current user to hold ``role``."""

    async def dependency(principal: Principal = Depends(CurrentUser)) -> Principal:
        if role not in principal.roles:
            raise ForbiddenError(f"Role '{role}' is required")
        return principal

    return dependency


def RequirePermission(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Build a dependency requiring the current principal to hold ``permission``.

    Works for either a user or a device token: authorization is by permission,
    never by hardcoding which principal type is allowed.
    """

    async def dependency(principal: Principal = Depends(CurrentPrincipal)) -> Principal:
        if permission not in principal.permissions:
            raise ForbiddenError(f"Permission '{permission}' is required")
        return principal

    return dependency
