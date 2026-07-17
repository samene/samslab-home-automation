"""SQLAlchemy repository implementing all Auth domain persistence operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.models import DeviceCredential, RefreshToken, Role, User


class AuthRepository:
    """Persist and query auth entities without leaking SQLAlchemy into services."""

    def __init__(self, session: AsyncSession) -> None:
        """Use one caller-owned session so service operations are transactional."""
        self._session = session

    # --- Users ---------------------------------------------------------------

    async def find_user_by_username(self, username: str) -> User | None:
        """Find one user by their unique username."""
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def find_user_by_id(self, user_id: UUID) -> User | None:
        """Find one user by UUID."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(self, user: User) -> User:
        """Stage a new user for commit by the application service."""
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user, attribute_names=["roles"])
        return user

    async def assign_role(self, user: User, role: Role) -> User:
        """Grant ``role`` to ``user`` if not already granted."""
        if role not in user.roles:
            user.roles.append(role)
            await self._session.flush()
        return user

    async def update_last_login(self, user: User, *, at: datetime) -> User:
        """Record a successful login time."""
        user.last_login = at
        await self._session.flush()
        await self._session.refresh(user)
        return user

    # --- Roles -----------------------------------------------------------------

    async def find_role_by_name(self, name: str) -> Role | None:
        """Find one role by its unique name."""
        result = await self._session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    async def create_role(self, role: Role) -> Role:
        """Stage a new role for commit by the caller; roles are not created via a REST endpoint."""
        self._session.add(role)
        await self._session.flush()
        return role

    # --- Refresh tokens ----------------------------------------------------------

    async def create_refresh_token(self, token: RefreshToken) -> RefreshToken:
        """Stage a new refresh token for commit by the application service."""
        self._session.add(token)
        await self._session.flush()
        return token

    async def find_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Find one refresh token by the hash of its plaintext value, regardless of state."""
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def find_active_refresh_token_by_hash(
        self, token_hash: str, *, as_of: datetime
    ) -> RefreshToken | None:
        """Find one refresh token by hash, only if unrevoked and unexpired as of ``as_of``.

        The active check is a SQL predicate, not a Python-side comparison, so
        it behaves identically whether ``expires_at`` round-trips as
        timezone-aware (PostgreSQL) or naive (SQLite in tests).
        """
        result = await self._session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > as_of,
            )
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: RefreshToken, *, at: datetime) -> RefreshToken:
        """Mark one refresh token revoked; safe to call more than once."""
        token.revoked_at = at
        await self._session.flush()
        return token

    # --- Device credentials -------------------------------------------------------

    async def find_device_credential_by_client_id(self, client_id: str) -> DeviceCredential | None:
        """Find one device credential by its unique client_id."""
        result = await self._session.execute(
            select(DeviceCredential).where(DeviceCredential.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def find_device_credential_by_device_id(self, device_id: UUID) -> DeviceCredential | None:
        """Find one device credential by the device it authenticates."""
        result = await self._session.execute(
            select(DeviceCredential).where(DeviceCredential.device_id == device_id)
        )
        return result.scalar_one_or_none()

    async def create_device_credential(self, credential: DeviceCredential) -> DeviceCredential:
        """Stage a new device credential for commit by the application service."""
        self._session.add(credential)
        await self._session.flush()
        return credential

    async def rotate_device_public_key(
        self, credential: DeviceCredential, *, public_key_pem: str, at: datetime
    ) -> DeviceCredential:
        """Replace a device credential's public key, recording when it rotated."""
        credential.public_key_pem = public_key_pem
        credential.last_rotated = at
        await self._session.flush()
        return credential
