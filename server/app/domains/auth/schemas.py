"""Typed, transport-independent contracts for the Auth domain."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class PrincipalType(StrEnum):
    """The two kinds of authenticated caller this system recognizes."""

    USER = "USER"
    DEVICE = "DEVICE"


class Principal(BaseModel):
    """The resolved identity and authorization claims carried by a validated token.

    This is the one shape ``CurrentUser``/``CurrentDevice``/``RequireRole``/
    ``RequirePermission`` all operate on — built purely from JWT claims, with
    no database access required to authorize a request.
    """

    principal_type: PrincipalType
    subject_id: str
    roles: frozenset[str] = frozenset()
    permissions: frozenset[str] = frozenset()
    device_id: UUID | None = None


class LoginRequest(BaseModel):
    """Username/password credentials submitted to ``POST /auth/login``."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    """A refresh token submitted to ``POST /auth/refresh`` or ``/auth/logout``."""

    refresh_token: str = Field(min_length=1)


class DeviceTokenRequest(BaseModel):
    """A signed JWT assertion submitted to ``POST /auth/device/token``.

    ``assertion`` proves possession of the private key matching this
    ``client_id``'s stored public key — see
    ``AuthService.issue_device_token``. A device can call this as often as
    it needs a fresh access token, since the assertion is minted fresh from
    a key the device holds permanently, unlike the access token it returns.
    """

    client_id: str = Field(min_length=1, max_length=100)
    assertion: str = Field(min_length=1)
