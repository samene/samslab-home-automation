"""Application service wrapping Auth use cases for REST controllers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.dto.auth_dto import (
    DeviceCredentialDTO,
    DeviceTokenDTO,
    TokenPairDTO,
    UserDTO,
)
from app.application.events.bus import EventBus
from app.application.events.domain_events import UserLoggedIn
from app.application.exceptions import translate_domain_error
from app.application.mappers.auth_mapper import to_device_credential_dto, to_user_dto
from app.domains.auth.exceptions import AuthDomainError
from app.domains.auth.schemas import LoginRequest, RefreshRequest
from app.domains.auth.service import AuthService, LoginResult
from app.domains.devices.exceptions import DeviceDomainError
from app.domains.devices.service import DeviceService


class AuthApplicationService:
    """Expose Auth use cases as DTOs, translating domain failures.

    Confirming a device exists before issuing or rotating its credential is a
    cross-domain rule (Auth + Devices), so it lives here rather than in
    either domain — the same pattern ``CommandApplicationService`` uses.
    """

    def __init__(
        self,
        auth_service: AuthService,
        device_service: DeviceService,
        event_bus: EventBus,
        *,
        access_token_ttl: timedelta,
    ) -> None:
        """Wrap both domain services; publish lifecycle events on the shared event bus."""
        self._auth = auth_service
        self._devices = device_service
        self._event_bus = event_bus
        self._access_token_ttl = access_token_ttl

    async def login(self, request: LoginRequest) -> TokenPairDTO:
        """Authenticate a user and issue a fresh access/refresh token pair."""
        try:
            result = await self._auth.login(request.username, request.password)
        except AuthDomainError as error:
            raise translate_domain_error(error) from error
        await self._event_bus.publish(
            UserLoggedIn(
                user_id=result.user.id,
                username=result.user.username,
                occurred_at=datetime.now(UTC),
            )
        )
        return self._to_token_pair(result)

    async def refresh(self, request: RefreshRequest) -> TokenPairDTO:
        """Rotate a valid refresh token for a fresh access/refresh token pair."""
        try:
            result = await self._auth.refresh(request.refresh_token)
        except AuthDomainError as error:
            raise translate_domain_error(error) from error
        return self._to_token_pair(result)

    async def logout(self, request: RefreshRequest) -> None:
        """Revoke a refresh token."""
        try:
            await self._auth.logout(request.refresh_token)
        except AuthDomainError as error:
            raise translate_domain_error(error) from error

    async def get_current_user(self, user_id: UUID) -> UserDTO:
        """Return the authenticated caller's own profile."""
        try:
            user = await self._auth.get_user(user_id)
        except AuthDomainError as error:
            raise translate_domain_error(error) from error
        return to_user_dto(user)

    async def issue_device_credential(self, device_id: UUID) -> DeviceCredentialDTO:
        """Create a new device credential after confirming the device exists."""
        try:
            await self._devices.get_device(device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        try:
            issued = await self._auth.issue_device_credential(device_id)
        except AuthDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_credential_dto(issued)

    async def rotate_device_key(self, device_id: UUID) -> DeviceCredentialDTO:
        """Replace an existing device credential's keypair after confirming the device exists."""
        try:
            await self._devices.get_device(device_id)
        except DeviceDomainError as error:
            raise translate_domain_error(error) from error
        try:
            issued = await self._auth.rotate_device_key(device_id)
        except AuthDomainError as error:
            raise translate_domain_error(error) from error
        return to_device_credential_dto(issued)

    async def issue_device_token(self, *, client_id: str, assertion: str) -> DeviceTokenDTO:
        """Exchange a signed JWT assertion for a short-lived device access token."""
        try:
            access_token = await self._auth.issue_device_token(
                client_id=client_id, assertion=assertion
            )
        except AuthDomainError as error:
            raise translate_domain_error(error) from error
        return DeviceTokenDTO(
            access_token=access_token, expires_in=int(self._access_token_ttl.total_seconds())
        )

    def _to_token_pair(self, result: LoginResult) -> TokenPairDTO:
        return TokenPairDTO(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_in=int(self._access_token_ttl.total_seconds()),
        )
