"""Mapping from Auth domain persistence entities to application DTOs."""

from __future__ import annotations

from app.application.dto.auth_dto import DeviceCredentialDTO, UserDTO
from app.domains.auth.models import User
from app.domains.auth.service import IssuedDeviceCredential


def to_user_dto(user: User) -> UserDTO:
    """Map a persisted user to its profile DTO."""
    return UserDTO(
        id=user.id,
        username=user.username,
        email=user.email,
        enabled=user.enabled,
        roles=sorted(role.name for role in user.roles),
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
    )


def to_device_credential_dto(issued: IssuedDeviceCredential) -> DeviceCredentialDTO:
    """Map a freshly issued device credential to its one-time-visible DTO."""
    return DeviceCredentialDTO(client_id=issued.client_id, private_key_b64=issued.private_key_b64)
