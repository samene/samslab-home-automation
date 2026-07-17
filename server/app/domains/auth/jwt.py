"""JWT encoding/decoding, independent of any transport.

No FastAPI, no Starlette, no HTTP concept anywhere in this module — a future
WebSocket handshake, gRPC interceptor, or MQTT connector can decode the same
tokens through the same ``JWTCodec``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt

from app.domains.auth.exceptions import ExpiredToken, InvalidToken


class JWTCodec:
    """Encode and decode signed JWTs against one issuer/audience/algorithm."""

    def __init__(
        self, *, secret: str, algorithm: str, issuer: str, audience: str, clock_skew_seconds: int
    ) -> None:
        """Bind the codec to one signing configuration for its lifetime."""
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._clock_skew_seconds = clock_skew_seconds

    def encode(
        self, *, subject: str, expires_in: timedelta, jti: str, claims: dict[str, Any]
    ) -> str:
        """Encode a signed token carrying the standard claims plus ``claims``."""
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + expires_in).timestamp()),
            "iss": self._issuer,
            "aud": self._audience,
            "jti": jti,
            **claims,
        }
        return pyjwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode(self, token: str) -> dict[str, Any]:
        """Decode and verify a token's signature, issuer, audience, and expiry."""
        try:
            payload: dict[str, Any] = pyjwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._clock_skew_seconds,
            )
        except pyjwt.ExpiredSignatureError as error:
            raise ExpiredToken("Token has expired") from error
        except pyjwt.InvalidTokenError as error:
            raise InvalidToken("Token is invalid") from error
        return payload
