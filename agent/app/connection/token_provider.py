"""Mints a fresh device access token from a permanently-held private key.

Replaces a static, pre-issued DEVICE_TOKEN: the old design meant an access
token minted once at provisioning time (15-minute TTL by default) that,
once expired with no live connection to renew it, left the agent with no
way to ever reconnect on its own. DEVICE_PRIVATE_KEY never expires and is
never transmitted anywhere — on every connection attempt the agent signs a
fresh, short-lived JWT assertion with it and exchanges that for a real
access token via ``POST {AUTH_TOKEN_URL}``, exactly like the server's own
MediaMTX JWT signing (``server/app/core/mediamtx_jwt.py``) mints tokens
from a key that never leaves the signer.
"""

from __future__ import annotations

import base64
import time
import uuid

import httpx
import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.config.settings import AgentSettings
from app.connection.exceptions import DeviceTokenRequestError
from app.metrics.registry import DEVICE_TOKEN_REQUEST_FAILURES_TOTAL, DEVICE_TOKEN_REQUESTS_TOTAL

#: Just long enough to survive the request round trip — this assertion is
#: single-use, minted fresh for every token request, never reused or stored.
_ASSERTION_TTL_SECONDS = 60
_REQUEST_TIMEOUT_SECONDS = 10.0


def _sign_assertion(*, client_id: str, private_key_pem: bytes) -> str:
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, RSAPrivateKey):
        raise DeviceTokenRequestError("DEVICE_PRIVATE_KEY must be an RSA private key")
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": client_id,
            "iat": now,
            "exp": now + _ASSERTION_TTL_SECONDS,
            "jti": str(uuid.uuid4()),
        },
        private_key,
        algorithm="RS256",
    )


async def fetch_device_token(settings: AgentSettings) -> str:
    """Sign a fresh assertion and exchange it for a device access token.

    Called on every connection attempt (see ``ConnectionManager.authenticate``),
    not just once at startup — this is what lets the agent recover from a
    connection that's been down far longer than any single access token's
    TTL, with no operator intervention.
    """
    DEVICE_TOKEN_REQUESTS_TOTAL.inc()
    try:
        private_key_pem = base64.b64decode(settings.device_private_key.get_secret_value())
        assertion = _sign_assertion(
            client_id=settings.device_client_id, private_key_pem=private_key_pem
        )
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.auth_token_url,
                json={"client_id": settings.device_client_id, "assertion": assertion},
            )
        response.raise_for_status()
        access_token = response.json()["access_token"]
    except DeviceTokenRequestError:
        DEVICE_TOKEN_REQUEST_FAILURES_TOTAL.inc()
        raise
    except Exception as error:
        DEVICE_TOKEN_REQUEST_FAILURES_TOTAL.inc()
        raise DeviceTokenRequestError(f"Failed to obtain a device token: {error}") from error

    if not isinstance(access_token, str) or not access_token:
        DEVICE_TOKEN_REQUEST_FAILURES_TOTAL.inc()
        raise DeviceTokenRequestError("Device token response was missing access_token")
    return access_token
