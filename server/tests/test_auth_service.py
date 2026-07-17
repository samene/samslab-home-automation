"""Service-level tests for the Auth domain: login, refresh, logout, device credentials."""

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

from app.core.database import Database
from app.domains.auth.exceptions import (
    DeviceCredentialAlreadyExists,
    DeviceCredentialNotFound,
    DisabledAccount,
    DisabledDevice,
    InvalidCredentials,
    InvalidToken,
)
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.models import DeviceCredential, Role, User
from app.domains.auth.passwords import hash_password
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import PrincipalType
from app.domains.auth.service import AuthService, IssuedDeviceCredential, decode_principal
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'auth_service.db'}")
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
def jwt_codec() -> JWTCodec:
    """Provide a deterministic JWT codec for service tests."""
    return JWTCodec(
        secret="a-sufficiently-long-test-signing-secret-value",
        algorithm="HS256",
        issuer="samslab",
        audience="samslab-clients",
        clock_skew_seconds=5,
    )


@pytest.fixture
def service(session: AsyncSession, jwt_codec: JWTCodec) -> AuthService:
    """Provide a transaction-scoped auth service for lifecycle tests."""
    return AuthService(
        AuthRepository(session),
        jwt_codec,
        access_token_ttl=timedelta(minutes=15),
        refresh_token_ttl=timedelta(days=14),
    )


async def create_user_with_role(
    session: AsyncSession,
    *,
    role_name: str = "Admin",
    enabled: bool = True,
    password: str = "s3cret-pw",
) -> User:
    """Register a user with one role, ready to log in."""
    repository = AuthRepository(session)
    role = Role(name=role_name, description="test role")
    session.add(role)
    await session.flush()
    user = await repository.create_user(
        User(
            username="sam",
            email="sam@example.com",
            password_hash=hash_password(password),
            enabled=enabled,
        )
    )
    await repository.assign_role(user, role)
    return user


# --- Login / refresh / logout ----------------------------------------------------


@pytest.mark.asyncio
async def test_login_succeeds_and_issues_a_valid_token_pair(
    service: AuthService, session: AsyncSession, jwt_codec: JWTCodec
) -> None:
    """A correct username/password pair returns a working access + refresh token."""
    await create_user_with_role(session)
    result = await service.login("sam", "s3cret-pw")
    assert result.user.username == "sam"
    assert result.user.last_login is not None
    principal = decode_principal(jwt_codec, result.access_token)
    assert principal.principal_type is PrincipalType.USER
    assert principal.roles == frozenset({"Admin"})
    assert "system.admin" in principal.permissions


@pytest.mark.asyncio
async def test_login_rejects_unknown_username(service: AuthService) -> None:
    """An unknown username fails the same way a wrong password would."""
    with pytest.raises(InvalidCredentials):
        await service.login("nobody", "whatever")


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(service: AuthService, session: AsyncSession) -> None:
    """A wrong password is rejected without revealing the username exists."""
    await create_user_with_role(session)
    with pytest.raises(InvalidCredentials):
        await service.login("sam", "wrong-password")


@pytest.mark.asyncio
async def test_login_rejects_a_disabled_account(
    service: AuthService, session: AsyncSession
) -> None:
    """A disabled account cannot log in even with the correct password."""
    await create_user_with_role(session, enabled=False)
    with pytest.raises(DisabledAccount):
        await service.login("sam", "s3cret-pw")


@pytest.mark.asyncio
async def test_refresh_rotates_the_token_and_invalidates_the_old_one(
    service: AuthService, session: AsyncSession
) -> None:
    """Refreshing issues a new pair and revokes the token that was presented."""
    await create_user_with_role(session)
    first = await service.login("sam", "s3cret-pw")
    second = await service.refresh(first.refresh_token)
    assert second.refresh_token != first.refresh_token
    with pytest.raises(InvalidToken):
        await service.refresh(first.refresh_token)


@pytest.mark.asyncio
async def test_refresh_rejects_an_unknown_token(service: AuthService) -> None:
    """A refresh token that was never issued is rejected."""
    with pytest.raises(InvalidToken):
        await service.refresh("not-a-real-refresh-token")


@pytest.mark.asyncio
async def test_refresh_rejects_a_token_for_a_now_disabled_account(
    service: AuthService, session: AsyncSession
) -> None:
    """A previously valid refresh token stops working once the account is disabled."""
    user = await create_user_with_role(session)
    result = await service.login("sam", "s3cret-pw")
    user.enabled = False
    await session.flush()
    with pytest.raises(DisabledAccount):
        await service.refresh(result.refresh_token)


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token(
    service: AuthService, session: AsyncSession
) -> None:
    """Logging out makes the refresh token unusable afterward."""
    await create_user_with_role(session)
    result = await service.login("sam", "s3cret-pw")
    await service.logout(result.refresh_token)
    with pytest.raises(InvalidToken):
        await service.refresh(result.refresh_token)


@pytest.mark.asyncio
async def test_logout_on_an_unknown_token_is_a_safe_no_op(service: AuthService) -> None:
    """Logging out with a token that was never issued does not raise."""
    await service.logout("never-issued-token")


@pytest.mark.asyncio
async def test_get_user_returns_the_full_profile(
    service: AuthService, session: AsyncSession
) -> None:
    """get_user returns the authenticated user's full record."""
    user = await create_user_with_role(session)
    fetched = await service.get_user(user.id)
    assert fetched.id == user.id


@pytest.mark.asyncio
async def test_get_user_raises_for_an_unknown_id(service: AuthService) -> None:
    """A user id with no matching row raises InvalidCredentials."""
    with pytest.raises(InvalidCredentials):
        await service.get_user(uuid4())


# --- Device credentials and tokens -----------------------------------------------


def _sign_assertion(
    issued: IssuedDeviceCredential, *, client_id: str | None = None, ttl_seconds: int = 60
) -> str:
    """Sign a self-assertion the way a real agent would with its private key.

    ``client_id`` can be overridden to build a deliberately-mismatched
    assertion for negative tests.
    """
    private_key = serialization.load_pem_private_key(
        base64.b64decode(issued.private_key_b64), password=None
    )
    assert isinstance(private_key, rsa.RSAPrivateKey)
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": client_id if client_id is not None else issued.client_id,
            "iat": now,
            "exp": now + ttl_seconds,
        },
        private_key,
        algorithm="RS256",
    )


@pytest.mark.asyncio
async def test_issue_device_token_round_trip(
    service: AuthService, session: AsyncSession, jwt_codec: JWTCodec
) -> None:
    """A freshly issued device credential can sign an assertion for a valid device token."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await service.issue_device_credential(device.id)
    token = await service.issue_device_token(
        client_id=issued.client_id, assertion=_sign_assertion(issued)
    )
    principal = service.validate_device_token(token)
    assert principal.principal_type is PrincipalType.DEVICE
    assert principal.device_id == device.id
    assert principal.roles == frozenset({"Agent"})
    assert "commands.execute" in principal.permissions

    # Also reachable through the pure decode_principal function directly.
    assert decode_principal(jwt_codec, token) == principal


@pytest.mark.asyncio
async def test_issue_device_token_rejects_an_assertion_signed_by_the_wrong_key(
    service: AuthService, session: AsyncSession
) -> None:
    """An assertion signed by a different keypair for a real client_id is rejected."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await service.issue_device_credential(device.id)
    other_device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "other-node", "hostname": "o.local", "display_name": "Other"}
        )
    )
    other_issued = await service.issue_device_credential(other_device.id)
    forged = _sign_assertion(other_issued, client_id=issued.client_id)
    with pytest.raises(InvalidCredentials):
        await service.issue_device_token(client_id=issued.client_id, assertion=forged)


@pytest.mark.asyncio
async def test_issue_device_token_rejects_an_assertion_with_a_mismatched_subject(
    service: AuthService, session: AsyncSession
) -> None:
    """The assertion's own sub claim must match the client_id it's presented for."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await service.issue_device_credential(device.id)
    mismatched = _sign_assertion(issued, client_id="someone-else")
    with pytest.raises(InvalidCredentials):
        await service.issue_device_token(client_id=issued.client_id, assertion=mismatched)


@pytest.mark.asyncio
async def test_issue_device_token_rejects_an_expired_assertion(
    service: AuthService, session: AsyncSession
) -> None:
    """An assertion past its own exp claim is rejected, however valid its signature."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await service.issue_device_credential(device.id)
    expired = _sign_assertion(issued, ttl_seconds=-1)
    with pytest.raises(InvalidCredentials):
        await service.issue_device_token(client_id=issued.client_id, assertion=expired)


@pytest.mark.asyncio
async def test_issue_device_token_rejects_unknown_client_id(service: AuthService) -> None:
    """An unknown client_id is rejected before any signature is even checked."""
    with pytest.raises(InvalidCredentials):
        await service.issue_device_token(client_id="not-a-real-client", assertion="anything")


@pytest.mark.asyncio
async def test_issue_device_token_rejects_a_disabled_credential(
    service: AuthService, session: AsyncSession
) -> None:
    """A disabled device credential cannot be exchanged for a token."""
    repository = AuthRepository(session)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    credential = await repository.create_device_credential(
        DeviceCredential(
            device_id=uuid4(),
            client_id="client-1",
            public_key_pem=public_pem.decode("ascii"),
            enabled=False,
        )
    )
    now = int(time.time())
    assertion = pyjwt.encode(
        {"sub": "client-1", "iat": now, "exp": now + 60}, private_key, algorithm="RS256"
    )
    with pytest.raises(DisabledDevice):
        await service.issue_device_token(client_id=credential.client_id, assertion=assertion)


@pytest.mark.asyncio
async def test_issue_device_credential_rejects_a_second_issuance_for_the_same_device(
    service: AuthService, session: AsyncSession
) -> None:
    """A device that already has a credential cannot be issued a second one directly.

    Confirming the device is enabled/exists is the application layer's job;
    this exercises the domain-level backstop (a real database constraint)
    that fires even when that check is bypassed.
    """
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    await service.issue_device_credential(device.id)
    with pytest.raises(DeviceCredentialAlreadyExists):
        await service.issue_device_credential(device.id)


@pytest.mark.asyncio
async def test_rotate_device_key_invalidates_the_old_key(
    service: AuthService, session: AsyncSession
) -> None:
    """After rotation, only an assertion signed by the new key authenticates."""
    device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {"device_name": "garden-node", "hostname": "g.local", "display_name": "Garden"}
        )
    )
    issued = await service.issue_device_credential(device.id)
    rotated = await service.rotate_device_key(device.id)
    assert rotated.client_id == issued.client_id
    assert rotated.private_key_b64 != issued.private_key_b64

    await service.issue_device_token(
        client_id=rotated.client_id, assertion=_sign_assertion(rotated)
    )
    with pytest.raises(InvalidCredentials):
        await service.issue_device_token(
            client_id=issued.client_id, assertion=_sign_assertion(issued)
        )


@pytest.mark.asyncio
async def test_rotate_device_key_raises_when_no_credential_exists(service: AuthService) -> None:
    """Rotating a device with no credential yet raises DeviceCredentialNotFound."""
    with pytest.raises(DeviceCredentialNotFound):
        await service.rotate_device_key(uuid4())


def test_validate_device_token_rejects_a_user_token(
    service: AuthService, jwt_codec: JWTCodec
) -> None:
    """validate_device_token refuses a token whose principal_type is USER."""
    user_token = jwt_codec.encode(
        subject=str(uuid4()),
        expires_in=timedelta(minutes=5),
        jti="jti-1",
        claims={"principal_type": "USER", "role": ["Admin"], "permissions": []},
    )
    with pytest.raises(InvalidToken):
        service.validate_device_token(user_token)
