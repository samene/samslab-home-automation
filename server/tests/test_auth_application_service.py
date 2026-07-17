"""Tests for AuthApplicationService: DTOs, event publishing, error translation."""

from __future__ import annotations

import base64
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.auth_dto import DeviceCredentialDTO, TokenPairDTO, UserDTO
from app.application.events.bus import EventBus
from app.application.events.domain_events import UserLoggedIn
from app.application.exceptions import (
    DeviceCredentialAlreadyExistsError,
    DeviceCredentialNotFoundError,
    DeviceNotFoundError,
    DisabledAccountError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from app.application.services.auth_service import AuthApplicationService
from app.core.database import Database
from app.domains.auth.exceptions import InvalidToken
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.models import Role, User
from app.domains.auth.passwords import hash_password
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import LoginRequest, RefreshRequest
from app.domains.auth.service import AuthService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'auth_app.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """Provide one transaction-scoped session shared by a test's fixtures and body."""
    async with database.session_factory() as session:
        yield session
        try:
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.fixture
def event_bus() -> EventBus:
    """Provide a fresh, unshared event bus so tests can assert on exactly what fired."""
    return EventBus()


@pytest.fixture
def app_service(session: AsyncSession, event_bus: EventBus) -> AuthApplicationService:
    """Provide an auth application service wired to the shared session and event bus."""
    jwt_codec = JWTCodec(
        secret="a-sufficiently-long-test-signing-secret-value",
        algorithm="HS256",
        issuer="samslab",
        audience="samslab-clients",
        clock_skew_seconds=5,
    )
    auth_service = AuthService(
        AuthRepository(session),
        jwt_codec,
        access_token_ttl=timedelta(minutes=15),
        refresh_token_ttl=timedelta(days=14),
    )
    return AuthApplicationService(
        auth_service,
        DeviceService(DeviceRepository(session)),
        event_bus,
        access_token_ttl=timedelta(minutes=15),
    )


async def seed_user(session: AsyncSession, *, enabled: bool = True) -> User:
    """Register a user with the Admin role for application-service tests."""
    repository = AuthRepository(session)
    role = Role(name="Admin", description="test role")
    session.add(role)
    await session.flush()
    user = await repository.create_user(
        User(
            username="sam",
            email="sam@example.com",
            password_hash=hash_password("s3cret-pw"),
            enabled=enabled,
        )
    )
    await repository.assign_role(user, role)
    return user


@pytest.mark.asyncio
async def test_login_returns_token_pair_dto_and_publishes_event(
    app_service: AuthApplicationService, session: AsyncSession, event_bus: EventBus
) -> None:
    """A successful login returns a TokenPairDTO and publishes UserLoggedIn."""
    received: list[UserLoggedIn] = []
    event_bus.subscribe(UserLoggedIn, received.append)
    user = await seed_user(session)

    result = await app_service.login(LoginRequest(username="sam", password="s3cret-pw"))

    assert isinstance(result, TokenPairDTO)
    assert result.token_type == "bearer"
    assert result.expires_in == int(timedelta(minutes=15).total_seconds())
    assert len(received) == 1
    assert received[0].user_id == user.id
    assert received[0].username == "sam"


@pytest.mark.asyncio
async def test_login_translates_invalid_credentials(app_service: AuthApplicationService) -> None:
    """A login failure surfaces as the application's InvalidCredentialsError."""
    with pytest.raises(InvalidCredentialsError):
        await app_service.login(LoginRequest(username="nobody", password="whatever"))


@pytest.mark.asyncio
async def test_login_translates_disabled_account(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """A disabled account's login failure surfaces as DisabledAccountError."""
    await seed_user(session, enabled=False)
    with pytest.raises(DisabledAccountError):
        await app_service.login(LoginRequest(username="sam", password="s3cret-pw"))


@pytest.mark.asyncio
async def test_refresh_returns_a_new_token_pair(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """Refresh returns a fresh TokenPairDTO with the same expires_in contract."""
    await seed_user(session)
    login_result = await app_service.login(LoginRequest(username="sam", password="s3cret-pw"))
    refreshed = await app_service.refresh(RefreshRequest(refresh_token=login_result.refresh_token))
    assert isinstance(refreshed, TokenPairDTO)
    assert refreshed.refresh_token != login_result.refresh_token


@pytest.mark.asyncio
async def test_refresh_translates_invalid_token(app_service: AuthApplicationService) -> None:
    """An unknown refresh token surfaces as the application's InvalidTokenError."""
    with pytest.raises(InvalidTokenError):
        await app_service.refresh(RefreshRequest(refresh_token="never-issued"))


@pytest.mark.asyncio
async def test_logout_revokes_and_is_idempotent(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """Logout succeeds for a real token and is a no-op for an already-revoked one."""
    await seed_user(session)
    login_result = await app_service.login(LoginRequest(username="sam", password="s3cret-pw"))
    await app_service.logout(RefreshRequest(refresh_token=login_result.refresh_token))
    await app_service.logout(RefreshRequest(refresh_token=login_result.refresh_token))


@pytest.mark.asyncio
async def test_logout_translates_a_domain_error(session: AsyncSession, event_bus: EventBus) -> None:
    """logout's error-translation branch fires even though the real domain call never raises.

    Exercised via a stub domain service, the same technique used for
    ``CommandApplicationService``'s analogous defensive branch.
    """
    jwt_codec = JWTCodec(
        secret="a-sufficiently-long-test-signing-secret-value",
        algorithm="HS256",
        issuer="samslab",
        audience="samslab-clients",
        clock_skew_seconds=5,
    )

    class _FailingAuthService(AuthService):
        async def logout(self, refresh_token: str) -> None:
            raise InvalidToken("simulated failure")

    stub_service = AuthApplicationService(
        _FailingAuthService(
            AuthRepository(session),
            jwt_codec,
            access_token_ttl=timedelta(minutes=15),
            refresh_token_ttl=timedelta(days=14),
        ),
        DeviceService(DeviceRepository(session)),
        event_bus,
        access_token_ttl=timedelta(minutes=15),
    )
    with pytest.raises(InvalidTokenError):
        await stub_service.logout(RefreshRequest(refresh_token="anything"))


@pytest.mark.asyncio
async def test_get_current_user_returns_user_dto(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """get_current_user maps the domain User to a UserDTO with resolved role names."""
    user = await seed_user(session)
    dto = await app_service.get_current_user(user.id)
    assert isinstance(dto, UserDTO)
    assert dto.username == "sam"
    assert dto.roles == ["Admin"]


@pytest.mark.asyncio
async def test_get_current_user_translates_not_found(app_service: AuthApplicationService) -> None:
    """A user id with no matching row surfaces as InvalidCredentialsError."""
    with pytest.raises(InvalidCredentialsError):
        await app_service.get_current_user(uuid4())


def _sign_assertion(issued: DeviceCredentialDTO, *, ttl_seconds: int = 60) -> str:
    """Sign a self-assertion the way a real agent would with its private key."""
    private_key = serialization.load_pem_private_key(
        base64.b64decode(issued.private_key_b64), password=None
    )
    assert isinstance(private_key, rsa.RSAPrivateKey)
    now = int(time.time())
    return pyjwt.encode(
        {"sub": issued.client_id, "iat": now, "exp": now + ttl_seconds},
        private_key,
        algorithm="RS256",
    )


@pytest.mark.asyncio
async def test_issue_and_rotate_device_credential_return_dtos(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """Device credential issuance and rotation both return DeviceCredentialDTOs."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await app_service.issue_device_credential(device.id)
    assert isinstance(issued, DeviceCredentialDTO)

    rotated = await app_service.rotate_device_key(device.id)
    assert rotated.client_id == issued.client_id
    assert rotated.private_key_b64 != issued.private_key_b64


@pytest.mark.asyncio
async def test_rotate_device_key_translates_credential_not_found(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """Rotating a real device with no credential yet surfaces as DeviceCredentialNotFoundError."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    with pytest.raises(DeviceCredentialNotFoundError):
        await app_service.rotate_device_key(device.id)


@pytest.mark.asyncio
async def test_rotate_device_key_translates_device_not_found(
    app_service: AuthApplicationService,
) -> None:
    """Rotating a device that does not exist at all surfaces as DeviceNotFoundError."""
    with pytest.raises(DeviceNotFoundError):
        await app_service.rotate_device_key(uuid4())


@pytest.mark.asyncio
async def test_issue_device_credential_translates_device_not_found(
    app_service: AuthApplicationService,
) -> None:
    """Issuing a credential for a device that does not exist surfaces as DeviceNotFoundError."""
    with pytest.raises(DeviceNotFoundError):
        await app_service.issue_device_credential(uuid4())


@pytest.mark.asyncio
async def test_issue_device_credential_translates_already_exists(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """Issuing a second credential for the same device surfaces as a conflict."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    await app_service.issue_device_credential(device.id)
    with pytest.raises(DeviceCredentialAlreadyExistsError):
        await app_service.issue_device_credential(device.id)


@pytest.mark.asyncio
async def test_issue_device_token_returns_device_token_dto(
    app_service: AuthApplicationService, session: AsyncSession
) -> None:
    """Exchanging device credentials for a token returns a DeviceTokenDTO."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await app_service.issue_device_credential(device.id)
    token_dto = await app_service.issue_device_token(
        client_id=issued.client_id, assertion=_sign_assertion(issued)
    )
    assert token_dto.token_type == "bearer"
    assert token_dto.access_token


@pytest.mark.asyncio
async def test_issue_device_token_translates_invalid_credentials(
    app_service: AuthApplicationService,
) -> None:
    """An unknown client_id surfaces as InvalidCredentialsError."""
    with pytest.raises(InvalidCredentialsError):
        await app_service.issue_device_token(client_id="unknown", assertion="whatever")
