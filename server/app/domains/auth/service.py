"""Transactional Auth domain application service.

Nothing here imports FastAPI or any other transport. ``decode_principal`` in
particular is a pure function so a future WebSocket handshake, gRPC
interceptor, or MQTT connector can validate the same tokens without ever
touching a database session.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.exc import IntegrityError

from app.domains.auth.exceptions import (
    DeviceCredentialAlreadyExists,
    DeviceCredentialNotFound,
    DisabledAccount,
    DisabledDevice,
    InvalidCredentials,
    InvalidToken,
)
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.models import DeviceCredential, RefreshToken, User
from app.domains.auth.passwords import verify_password
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import Principal, PrincipalType
from app.domains.auth.tokens import generate_refresh_token, hash_opaque_token, new_jti

#: Devices authenticate assertions with this algorithm only — see
#: issue_device_token's note on why the algorithm can never be attacker-chosen.
DEVICE_ASSERTION_ALGORITHM = "RS256"


@dataclass(frozen=True, slots=True)
class LoginResult:
    """The outcome of a successful login or refresh: a user and a fresh token pair."""

    user: User
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class IssuedDeviceCredential:
    """A device credential's private key, available only at issuance/rotation.

    ``private_key_b64`` is the base64 encoding of a PKCS8 PEM RSA private
    key — base64 so it survives being pasted into a bash-sourced ``.env``
    unscathed, the same reason ``MEDIAMTX_JWT_PRIVATE_KEY`` is encoded this
    way (see ``app/core/mediamtx_jwt.py``). Only the matching public key is
    ever persisted server-side; this value is never stored or recoverable
    after this call returns.
    """

    client_id: str
    private_key_b64: str


def _generate_device_keypair() -> tuple[str, str]:
    """Generate a fresh RSA keypair; return (public_key_pem, private_key_b64)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return public_pem.decode("ascii"), base64.b64encode(private_pem).decode("ascii")


def decode_principal(jwt_codec: JWTCodec, token: str) -> Principal:
    """Decode a bearer token into its ``Principal`` claims.

    Pure and database-free: the token's ``role``/``permissions`` claims were
    already resolved at issuance time, so authorizing a request never needs
    a database round-trip.
    """
    claims = jwt_codec.decode(token)
    device_id = claims.get("device_id")
    return Principal(
        principal_type=PrincipalType(claims["principal_type"]),
        subject_id=claims["sub"],
        roles=frozenset(claims.get("role", [])),
        permissions=frozenset(claims.get("permissions", [])),
        device_id=UUID(device_id) if device_id else None,
    )


class AuthService:
    """Coordinate Auth domain use cases: credential checks, tokens, and rotation."""

    def __init__(
        self,
        repository: AuthRepository,
        jwt_codec: JWTCodec,
        *,
        access_token_ttl: timedelta,
        refresh_token_ttl: timedelta,
    ) -> None:
        """Inject the repository and the JWT codec/TTLs used to mint tokens."""
        self._repository = repository
        self._jwt_codec = jwt_codec
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl

    async def login(self, username: str, password: str) -> LoginResult:
        """Verify credentials and issue a fresh access/refresh token pair.

        Failure for an unknown username and failure for a wrong password are
        deliberately indistinguishable, to avoid revealing whether a username
        is registered.
        """
        user = await self._repository.find_user_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentials("Invalid username or password")
        if not user.enabled:
            raise DisabledAccount("This account is disabled")
        user = await self._repository.update_last_login(user, at=datetime.now(UTC))
        return await self._issue_login_result(user)

    async def refresh(self, refresh_token: str) -> LoginResult:
        """Rotate a valid, unexpired refresh token for a fresh token pair."""
        stored = await self._repository.find_active_refresh_token_by_hash(
            hash_opaque_token(refresh_token), as_of=datetime.now(UTC)
        )
        if stored is None:
            raise InvalidToken("Refresh token is invalid, expired, or already used")
        user = await self._repository.find_user_by_id(stored.user_id)
        if user is None or not user.enabled:
            raise DisabledAccount("This account is disabled")
        await self._repository.revoke_refresh_token(stored, at=datetime.now(UTC))
        return await self._issue_login_result(user)

    async def logout(self, refresh_token: str) -> None:
        """Revoke a refresh token; a already-revoked or unknown token is a no-op."""
        stored = await self._repository.find_refresh_token_by_hash(hash_opaque_token(refresh_token))
        if stored is not None and stored.revoked_at is None:
            await self._repository.revoke_refresh_token(stored, at=datetime.now(UTC))

    async def get_user(self, user_id: UUID) -> User:
        """Return the full profile for an already-authenticated user."""
        user = await self._repository.find_user_by_id(user_id)
        if user is None:
            raise InvalidCredentials("The authenticated user no longer exists")
        return user

    async def issue_device_credential(self, device_id: UUID) -> IssuedDeviceCredential:
        """Create a new device credential, returning its private key exactly once.

        Confirming the device itself exists is a cross-domain concern and is
        the caller's (application layer's) responsibility, not this domain's;
        a device that doesn't exist still surfaces safely here via the
        ``device_credentials.device_id`` foreign key raising ``IntegrityError``.
        """
        public_key_pem, private_key_b64 = _generate_device_keypair()
        credential = DeviceCredential(
            device_id=device_id,
            client_id=f"device-{device_id}",
            public_key_pem=public_key_pem,
        )
        try:
            credential = await self._repository.create_device_credential(credential)
        except IntegrityError as error:
            raise DeviceCredentialAlreadyExists(
                f"Device '{device_id}' already has a credential, or does not exist"
            ) from error
        return IssuedDeviceCredential(
            client_id=credential.client_id, private_key_b64=private_key_b64
        )

    async def rotate_device_key(self, device_id: UUID) -> IssuedDeviceCredential:
        """Replace an existing device credential's keypair, returning the new private key once."""
        credential = await self._repository.find_device_credential_by_device_id(device_id)
        if credential is None:
            raise DeviceCredentialNotFound(f"Device '{device_id}' has no credential to rotate")
        public_key_pem, private_key_b64 = _generate_device_keypair()
        credential = await self._repository.rotate_device_public_key(
            credential, public_key_pem=public_key_pem, at=datetime.now(UTC)
        )
        return IssuedDeviceCredential(
            client_id=credential.client_id, private_key_b64=private_key_b64
        )

    async def issue_device_token(self, *, client_id: str, assertion: str) -> str:
        """Exchange a signed JWT assertion (proof of the device's private key) for an access token.

        The assertion must be signed RS256 with the private key matching
        this ``client_id``'s stored public key, and must claim ``sub ==
        client_id`` (defense in depth beyond the signature check alone, and
        cheap to verify). The algorithm is pinned to RS256 explicitly — never
        read from the assertion's own header — so a forged assertion can't
        claim ``alg: none`` or an HMAC algorithm keyed by the public PEM
        (the classic JWT "algorithm confusion" attack).
        """
        credential = await self._repository.find_device_credential_by_client_id(client_id)
        if credential is None:
            raise InvalidCredentials("Invalid device client_id or assertion")
        try:
            claims = pyjwt.decode(
                assertion,
                credential.public_key_pem,
                algorithms=[DEVICE_ASSERTION_ALGORITHM],
            )
        except pyjwt.InvalidTokenError as error:
            raise InvalidCredentials("Invalid device client_id or assertion") from error
        if claims.get("sub") != client_id:
            raise InvalidCredentials("Invalid device client_id or assertion")
        if not credential.enabled:
            raise DisabledDevice("This device credential is disabled")
        role_names = ["Agent"]
        return self._issue_access_token(
            subject=str(credential.device_id),
            principal_type=PrincipalType.DEVICE,
            roles=role_names,
            device_id=credential.device_id,
        )

    def validate_device_token(self, token: str) -> Principal:
        """Decode a token and confirm it belongs to a device, not a user."""
        principal = decode_principal(self._jwt_codec, token)
        if principal.principal_type is not PrincipalType.DEVICE:
            raise InvalidToken("A device token is required")
        return principal

    async def _issue_login_result(self, user: User) -> LoginResult:
        role_names = [role.name for role in user.roles]
        access_token = self._issue_access_token(
            subject=str(user.id), principal_type=PrincipalType.USER, roles=role_names
        )
        refresh_token = generate_refresh_token()
        await self._repository.create_refresh_token(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_opaque_token(refresh_token),
                expires_at=datetime.now(UTC) + self._refresh_token_ttl,
            )
        )
        return LoginResult(user=user, access_token=access_token, refresh_token=refresh_token)

    def _issue_access_token(
        self,
        *,
        subject: str,
        principal_type: PrincipalType,
        roles: list[str],
        device_id: UUID | None = None,
    ) -> str:
        claims: dict[str, object] = {
            "role": roles,
            "permissions": sorted(permissions_for_roles(roles)),
            "principal_type": principal_type.value,
        }
        if device_id is not None:
            claims["device_id"] = str(device_id)
        return self._jwt_codec.encode(
            subject=subject, expires_in=self._access_token_ttl, jti=new_jti(), claims=claims
        )
