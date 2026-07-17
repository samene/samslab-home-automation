"""Public JWKS endpoint that MediaMTX pulls once to validate playback JWTs.

No authentication on this route: a JWKS endpoint is conventionally public by
design — it publishes only public key material (see
``app/core/mediamtx_jwt.py``), never anything that needs protecting.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.mediamtx_jwt import MediaMTXJWTSigner

router = APIRouter(tags=["MediaMTX"])


@router.get("/.well-known/mediamtx-jwks.json", summary="Public key set for MediaMTX JWT auth")
async def get_mediamtx_jwks(request: Request) -> dict[str, object]:
    """Return an empty key set when MediaMTX JWT auth isn't configured, never an error."""
    signer: MediaMTXJWTSigner | None = request.app.state.container.mediamtx_jwt_signer()
    if signer is None:
        return {"keys": []}
    return signer.public_jwks()
