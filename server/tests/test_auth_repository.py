"""Repository and migration-metadata tests for the Auth domain."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.domains.auth.models import DeviceCredential, RefreshToken, Role, User
from app.domains.auth.repository import AuthRepository


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
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
def repository(session: AsyncSession) -> AuthRepository:
    """Provide a transaction-scoped repository for persistence-only tests."""
    return AuthRepository(session)


def build_user(username: str = "sam") -> User:
    """Build a transient User model for repository-only persistence tests."""
    return User(username=username, email=f"{username}@example.com", password_hash="hash")


# --- Users -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_find_user_by_username_and_id(repository: AuthRepository) -> None:
    """A created user round-trips through both lookup methods."""
    user = await repository.create_user(build_user())
    assert (await repository.find_user_by_username("sam")) is not None
    assert (await repository.find_user_by_id(user.id)) is not None
    assert (await repository.find_user_by_username("missing")) is None
    assert (await repository.find_user_by_id(uuid4())) is None


@pytest.mark.asyncio
async def test_assign_role_is_idempotent(repository: AuthRepository, session: AsyncSession) -> None:
    """Assigning the same role twice does not create a duplicate grant."""
    user = await repository.create_user(build_user())
    role = Role(name="Admin", description="x")
    session.add(role)
    await session.flush()

    await repository.assign_role(user, role)
    await repository.assign_role(user, role)

    assert [r.name for r in user.roles] == ["Admin"]


@pytest.mark.asyncio
async def test_update_last_login_sets_the_timestamp(repository: AuthRepository) -> None:
    """update_last_login records the given time and the user round-trips cleanly.

    SQLite (unlike PostgreSQL) does not preserve tzinfo across a round trip,
    so the comparison assumes UTC on the read-back naive value rather than
    asserting exact equality of the two Python objects.
    """
    user = await repository.create_user(build_user())
    at = datetime.now(UTC)
    updated = await repository.update_last_login(user, at=at)
    assert updated.last_login is not None
    assert updated.last_login.replace(tzinfo=UTC) == at
    assert updated.updated_at is not None


@pytest.mark.asyncio
async def test_find_role_by_name(repository: AuthRepository, session: AsyncSession) -> None:
    """A role is found by its unique name, or None if it doesn't exist."""
    role = Role(name="Viewer", description="read-only")
    session.add(role)
    await session.flush()

    assert (await repository.find_role_by_name("Viewer")) is not None
    assert (await repository.find_role_by_name("NotARole")) is None


# --- Refresh tokens ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_find_refresh_token_by_hash(repository: AuthRepository) -> None:
    """A created refresh token is found by the hash of its plaintext value."""
    user = await repository.create_user(build_user())
    token = await repository.create_refresh_token(
        RefreshToken(
            user_id=user.id, token_hash="hash-1", expires_at=datetime.now(UTC) + timedelta(days=1)
        )
    )
    found = await repository.find_refresh_token_by_hash("hash-1")
    assert found is not None
    assert found.id == token.id
    assert (await repository.find_refresh_token_by_hash("missing")) is None


@pytest.mark.asyncio
async def test_find_active_refresh_token_excludes_revoked_and_expired(
    repository: AuthRepository,
) -> None:
    """Only an unrevoked, unexpired token is considered active."""
    user = await repository.create_user(build_user())
    now = datetime.now(UTC)

    active = await repository.create_refresh_token(
        RefreshToken(user_id=user.id, token_hash="active", expires_at=now + timedelta(days=1))
    )
    revoked = await repository.create_refresh_token(
        RefreshToken(user_id=user.id, token_hash="revoked", expires_at=now + timedelta(days=1))
    )
    await repository.revoke_refresh_token(revoked, at=now)
    await repository.create_refresh_token(
        RefreshToken(user_id=user.id, token_hash="expired", expires_at=now - timedelta(days=1))
    )

    found_active = await repository.find_active_refresh_token_by_hash("active", as_of=now)
    assert found_active is not None
    assert found_active.id == active.id
    assert (await repository.find_active_refresh_token_by_hash("revoked", as_of=now)) is None
    assert (await repository.find_active_refresh_token_by_hash("expired", as_of=now)) is None


@pytest.mark.asyncio
async def test_revoke_refresh_token_is_safe_to_call_twice(repository: AuthRepository) -> None:
    """Revoking an already-revoked token just re-stamps revoked_at, without error."""
    user = await repository.create_user(build_user())
    token = await repository.create_refresh_token(
        RefreshToken(
            user_id=user.id, token_hash="hash-1", expires_at=datetime.now(UTC) + timedelta(days=1)
        )
    )
    first = datetime.now(UTC)
    await repository.revoke_refresh_token(token, at=first)
    second = datetime.now(UTC)
    revoked_again = await repository.revoke_refresh_token(token, at=second)
    assert revoked_again.revoked_at == second


# --- Device credentials -------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_find_device_credential(repository: AuthRepository) -> None:
    """A created device credential is found by client_id and by device_id."""
    device_id = uuid4()
    credential = await repository.create_device_credential(
        DeviceCredential(device_id=device_id, client_id="client-1", public_key_pem="pem-1")
    )
    assert (await repository.find_device_credential_by_client_id("client-1")) is not None
    found_by_device = await repository.find_device_credential_by_device_id(device_id)
    assert found_by_device is not None
    assert found_by_device.id == credential.id
    assert (await repository.find_device_credential_by_client_id("missing")) is None
    assert (await repository.find_device_credential_by_device_id(uuid4())) is None


@pytest.mark.asyncio
async def test_rotate_device_public_key_replaces_key_and_stamps_last_rotated(
    repository: AuthRepository,
) -> None:
    """Rotating a device credential updates its public key and last_rotated time."""
    credential = await repository.create_device_credential(
        DeviceCredential(device_id=uuid4(), client_id="client-1", public_key_pem="old-pem")
    )
    at = datetime.now(UTC)
    rotated = await repository.rotate_device_public_key(credential, public_key_pem="new-pem", at=at)
    assert rotated.public_key_pem == "new-pem"
    assert rotated.last_rotated == at


# --- Migration ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_metadata_contains_required_tables(database: Database) -> None:
    """The model metadata used by the migration exposes every auth table."""
    async with database._engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert {
        "users",
        "roles",
        "permissions",
        "user_roles",
        "device_credentials",
        "refresh_tokens",
    }.issubset(table_names)
