"""Opaque secret generation and hashing, distinct from JWT access-token encoding.

Refresh tokens are random, opaque strings — never JWTs — so only their
SHA-256 hash needs to be persisted; the plaintext is shown to the caller
exactly once, at issuance, and is not recoverable from the database
afterward. Device credentials are asymmetric keypairs instead (see
``AuthService.issue_device_credential``), so they have no equivalent
opaque-secret helper here — there's nothing to hash, only a public key to
store as-is.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4


def new_jti() -> str:
    """Generate a fresh, unique JWT ID for the ``jti`` claim."""
    return str(uuid4())


def generate_refresh_token() -> str:
    """Generate a new, cryptographically random opaque refresh token."""
    return secrets.token_urlsafe(64)


def hash_opaque_token(token: str) -> str:
    """Hash an opaque token for at-rest storage; the digest is not reversible.

    A fast digest (not Argon2) is appropriate here: unlike a user password,
    an opaque refresh token already has 64 bytes of secure random entropy,
    so it is not subject to offline dictionary/brute-force attack the way a
    human-chosen password is.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
