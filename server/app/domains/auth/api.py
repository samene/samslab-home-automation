"""FastAPI delivery adapter for Auth domain endpoints.

Contains no business logic: each route only resolves the application
service, forwards validated input to it, and returns the DTO it produces.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.application.dto.auth_dto import DeviceTokenDTO, TokenPairDTO, UserDTO
from app.application.services.auth_service import AuthApplicationService
from app.domains.auth.dependencies import CurrentUser, get_auth_application_service
from app.domains.auth.schemas import DeviceTokenRequest, LoginRequest, Principal, RefreshRequest

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenPairDTO)
async def login(
    request: LoginRequest,
    service: AuthApplicationService = Depends(get_auth_application_service),
) -> TokenPairDTO:
    """Authenticate a user and issue a fresh access/refresh token pair."""
    return await service.login(request)


@router.post("/refresh", response_model=TokenPairDTO)
async def refresh(
    request: RefreshRequest,
    service: AuthApplicationService = Depends(get_auth_application_service),
) -> TokenPairDTO:
    """Rotate a valid refresh token for a fresh access/refresh token pair."""
    return await service.refresh(request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: RefreshRequest,
    service: AuthApplicationService = Depends(get_auth_application_service),
) -> None:
    """Revoke a refresh token."""
    await service.logout(request)


@router.get("/me", response_model=UserDTO)
async def me(
    principal: Principal = Depends(CurrentUser),
    service: AuthApplicationService = Depends(get_auth_application_service),
) -> UserDTO:
    """Return the authenticated caller's own profile."""
    return await service.get_current_user(UUID(principal.subject_id))


@router.post("/device/token", response_model=DeviceTokenDTO)
async def issue_device_token(
    request: DeviceTokenRequest,
    service: AuthApplicationService = Depends(get_auth_application_service),
) -> DeviceTokenDTO:
    """Exchange a private-key-signed JWT assertion for a short-lived device access token.

    A device can call this as often as it needs a fresh token — including
    immediately after a long disconnection — since the assertion is minted
    fresh from a key it holds permanently, never transmitted or stored
    server-side.
    """
    return await service.issue_device_token(
        client_id=request.client_id, assertion=request.assertion
    )
