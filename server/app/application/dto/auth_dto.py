"""Auth data transfer objects: the only auth shapes REST controllers ever see."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class UserDTO(BaseModel):
    """A user's own profile, as returned by ``GET /auth/me``."""

    id: UUID
    username: str
    email: str
    enabled: bool
    roles: list[str]
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None


class TokenPairDTO(BaseModel):
    """An access/refresh token pair, as returned by login and refresh."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class DeviceTokenDTO(BaseModel):
    """A device access token; devices re-authenticate rather than holding a refresh token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class DeviceCredentialDTO(BaseModel):
    """A device credential's client_id and private key, available only at issuance/rotation."""

    client_id: str
    private_key_b64: str
