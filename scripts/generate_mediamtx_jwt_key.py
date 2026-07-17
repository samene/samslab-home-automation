#!/usr/bin/env python3.13
"""Generate the RSA keypair used to sign MediaMTX playback JWTs.

This key is distinct from the app's own user/device auth (HS256, symmetric
``JWT_SECRET``) — MediaMTX validates playback JWTs against a JWKS endpoint
(``GET /.well-known/mediamtx-jwks.json``, see ``app/core/mediamtx_jwt.py``),
which can only ever publish a *public* key. Reusing a symmetric secret here
would mean publishing it to anyone who fetches that URL.

Usage (run from the repo root; no server virtualenv or database required —
this script only needs ``cryptography``, already a transitive dependency of
``pyjwt[crypto]``):

    python scripts/generate_mediamtx_jwt_key.py

Paste the printed ``MEDIAMTX_JWT_PRIVATE_KEY`` line into the server's
``.env``. This key itself is server-only — the agent never holds it, and no
matching key needs generating or configuring on the agent side. But note:
MediaMTX only runs one ``authMethod`` at a time, so once mediamtx.yml sets it
to ``jwt`` (required for this feature), the agent's RTSP *publish*
connection needs a JWT too — that part is already handled in code (a
publish token rides along in every ``camera.stream.start`` command's
payload, see ``docs/agent/CAMERA.md``'s "Agent publish authentication"), not
something you configure here.

On the MediaMTX side, point ``authJWTJWKS`` (in ``mediamtx.yml``) at
``https://<your-server>/api/.well-known/mediamtx-jwks.json`` — the ``/api``
prefix matters in the hybrid deployment (see ``deployment/caddy/Caddyfile``):
Caddy only reverse-proxies ``/api/*`` to this backend, stripping the prefix
before forwarding, so the un-prefixed path 404s through the public domain
even though the backend's own route has no ``/api`` in it.
"""

from __future__ import annotations

from base64 import b64encode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    encoded = b64encode(pem).decode("ascii")

    print("Add this to the server's .env (never commit it):\n")
    print(f"MEDIAMTX_JWT_PRIVATE_KEY={encoded}")
    print(
        "\nIn mediamtx.yml, set authJWTJWKS to this server's "
        "/api/.well-known/mediamtx-jwks.json URL — the /api prefix matters, "
        "since Caddy only reverse-proxies /api/* to the backend (see "
        "deployment/caddy/Caddyfile). authJWTClaimKey's default, "
        "mediamtx_permissions, already matches what this app mints."
    )


if __name__ == "__main__":
    main()
