"""Signs short-lived JWTs for MediaMTX's JWT-based authentication.

MediaMTX validates these against a JWKS endpoint we expose ourselves
(``GET /.well-known/mediamtx-jwks.json``, see ``app/api/mediamtx_jwks.py``),
pulling the public key once and caching it — see ``authJWTJWKS`` in
``mediamtx.yml``. This is a deliberately separate signing key from the app's
own user/device auth (``app/domains/auth/jwt.py``, HS256 with a shared
secret): a JWKS endpoint can only ever publish a *public* key, so signing
these tokens with the app's symmetric ``JWT_SECRET`` would mean publishing
that secret to anyone who fetches the JWKS URL — including MediaMTX itself,
which has no need to ever see it. RS256 (asymmetric) is required precisely
so the private key never leaves this process.

Replaces the previous (and, per Chrome's 2022 removal of URL userinfo
support, non-functional) approach of embedding ``user:pass@host`` credentials
directly into the browser-facing playback URL.

MediaMTX only supports one active ``authMethod`` at a time — setting it to
``jwt`` (as this feature requires for browser reads) means the agent's RTSP
*publish* connection must authenticate with a JWT too, since there's no
"internal database" method left running alongside it to fall back to for
just that one action. So this module mints both **read** tokens (for the
browser, via ``CameraApplicationService``) and **publish** tokens (for the
agent, delivered as part of a ``camera.stream.start`` command's payload —
see ``CameraApplicationService.start_stream``); the only difference is the
``action`` claim and, typically, a much longer TTL for publish (a stream can
run for hours, and the agent has no token-refresh logic).
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from typing import Literal

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from jwt.algorithms import RSAAlgorithm

from app.config.settings import Settings

ALGORITHM = "RS256"
MediaMTXAction = Literal["read", "publish"]


@dataclass(frozen=True)
class MediaMTXJWTSigner:
    """Holds one RSA keypair and mints/publishes MediaMTX-compatible read tokens."""

    private_key: RSAPrivateKey
    key_id: str
    issuer: str | None
    audience: str | None

    @classmethod
    def from_base64_pem(
        cls,
        *,
        private_key_b64: str,
        key_id: str,
        issuer: str | None,
        audience: str | None,
    ) -> MediaMTXJWTSigner:
        """Decode a base64-encoded PKCS8 PEM private key (see ``.env`` for why base64)."""
        pem_bytes = base64.b64decode(private_key_b64)
        private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise ValueError("MEDIAMTX_JWT_PRIVATE_KEY must be an RSA private key")
        return cls(private_key=private_key, key_id=key_id, issuer=issuer, audience=audience)

    def mint_read_token(self, *, stream_path: str, ttl_seconds: float) -> str:
        """Mint a short-lived token granting read access to exactly one stream path."""
        return self._mint_token(action="read", stream_path=stream_path, ttl_seconds=ttl_seconds)

    def mint_publish_token(self, *, stream_path: str, ttl_seconds: float) -> str:
        """Mint a token granting publish access to exactly one stream path.

        Delivered to the agent as part of a ``camera.stream.start`` command's
        payload, never generated or held by the agent itself — the agent
        never sees this signing key, only the finished token.
        """
        return self._mint_token(action="publish", stream_path=stream_path, ttl_seconds=ttl_seconds)

    def _mint_token(self, *, action: MediaMTXAction, stream_path: str, ttl_seconds: float) -> str:
        now = int(time.time())
        payload: dict[str, object] = {
            "iat": now,
            "exp": now + max(1, int(ttl_seconds)),
            "jti": str(uuid.uuid4()),
            "mediamtx_permissions": [{"action": action, "path": stream_path}],
        }
        if self.issuer:
            payload["iss"] = self.issuer
        if self.audience:
            payload["aud"] = self.audience
        return pyjwt.encode(
            payload, self.private_key, algorithm=ALGORITHM, headers={"kid": self.key_id}
        )

    def public_jwks(self) -> dict[str, object]:
        """The public JWK Set MediaMTX fetches once to validate tokens minted above."""
        jwk = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        jwk["kid"] = self.key_id
        jwk["alg"] = ALGORITHM
        jwk["use"] = "sig"
        return {"keys": [jwk]}


def build_mediamtx_jwt_signer(settings: Settings) -> MediaMTXJWTSigner | None:
    """Build the signer from settings, or None when MediaMTX JWT auth isn't configured.

    A missing key is not an error — it mirrors how ``database_url``/``jwt_secret``
    are optional elsewhere in ``Settings``, so the app still starts (e.g. in tests,
    or before an operator has generated a MediaMTX keypair).
    """
    if settings.mediamtx_jwt_private_key is None:
        return None
    return MediaMTXJWTSigner.from_base64_pem(
        private_key_b64=settings.mediamtx_jwt_private_key.get_secret_value(),
        key_id=settings.mediamtx_jwt_key_id,
        issuer=settings.mediamtx_jwt_issuer,
        audience=settings.mediamtx_jwt_audience,
    )
