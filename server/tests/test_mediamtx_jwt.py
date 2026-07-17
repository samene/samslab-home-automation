"""Tests for MediaMTXJWTSigner: token minting, JWKS publication, and settings wiring."""

from __future__ import annotations

from base64 import b64encode

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.config.settings import Settings
from app.core.mediamtx_jwt import MediaMTXJWTSigner, build_mediamtx_jwt_signer


def _base64_pem(private_key: rsa.RSAPrivateKey) -> str:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return b64encode(pem).decode("ascii")


@pytest.fixture
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_from_base64_pem_round_trips_a_real_key(private_key: rsa.RSAPrivateKey) -> None:
    signer = MediaMTXJWTSigner.from_base64_pem(
        private_key_b64=_base64_pem(private_key), key_id="k1", issuer=None, audience=None
    )
    assert signer.key_id == "k1"
    assert signer.private_key.key_size == 2048


def test_from_base64_pem_rejects_a_non_rsa_key() -> None:
    ec_key = ec.generate_private_key(ec.SECP256R1())
    pem = ec_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="RSA"):
        MediaMTXJWTSigner.from_base64_pem(
            private_key_b64=b64encode(pem).decode("ascii"), key_id="k1", issuer=None, audience=None
        )


def test_mint_read_token_carries_the_mediamtx_permissions_claim(
    private_key: rsa.RSAPrivateKey,
) -> None:
    signer = MediaMTXJWTSigner(private_key=private_key, key_id="k1", issuer=None, audience=None)

    token = signer.mint_read_token(stream_path="camera", ttl_seconds=30)

    claims = pyjwt.decode(token, private_key.public_key(), algorithms=["RS256"])
    assert claims["mediamtx_permissions"] == [{"action": "read", "path": "camera"}]
    assert claims["exp"] - claims["iat"] == 30
    assert "iss" not in claims
    assert "aud" not in claims


def test_mint_read_token_includes_issuer_and_audience_when_configured(
    private_key: rsa.RSAPrivateKey,
) -> None:
    signer = MediaMTXJWTSigner(
        private_key=private_key, key_id="k1", issuer="samslab", audience="mediamtx"
    )

    token = signer.mint_read_token(stream_path="camera", ttl_seconds=30)

    claims = pyjwt.decode(
        token, private_key.public_key(), algorithms=["RS256"], issuer="samslab", audience="mediamtx"
    )
    assert claims["iss"] == "samslab"
    assert claims["aud"] == "mediamtx"


def test_mint_publish_token_carries_a_publish_permission(
    private_key: rsa.RSAPrivateKey,
) -> None:
    signer = MediaMTXJWTSigner(private_key=private_key, key_id="k1", issuer=None, audience=None)

    token = signer.mint_publish_token(stream_path="camera", ttl_seconds=3600)

    claims = pyjwt.decode(token, private_key.public_key(), algorithms=["RS256"])
    assert claims["mediamtx_permissions"] == [{"action": "publish", "path": "camera"}]
    assert claims["exp"] - claims["iat"] == 3600


def test_mint_read_token_sets_the_kid_header(private_key: rsa.RSAPrivateKey) -> None:
    signer = MediaMTXJWTSigner(private_key=private_key, key_id="my-kid", issuer=None, audience=None)

    token = signer.mint_read_token(stream_path="camera", ttl_seconds=30)

    assert pyjwt.get_unverified_header(token)["kid"] == "my-kid"


def test_public_jwks_exposes_only_public_key_material(private_key: rsa.RSAPrivateKey) -> None:
    signer = MediaMTXJWTSigner(private_key=private_key, key_id="k1", issuer=None, audience=None)

    jwks = signer.public_jwks()

    assert list(jwks) == ["keys"]
    keys = jwks["keys"]
    assert isinstance(keys, list)
    assert len(keys) == 1
    key = keys[0]
    assert key["kty"] == "RSA"
    assert key["kid"] == "k1"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert "n" in key and "e" in key
    assert "d" not in key  # the private exponent must never be published


def test_build_mediamtx_jwt_signer_returns_none_when_unconfigured() -> None:
    settings = Settings(ENVIRONMENT="test")
    assert build_mediamtx_jwt_signer(settings) is None


def test_build_mediamtx_jwt_signer_builds_a_working_signer_from_settings(
    private_key: rsa.RSAPrivateKey,
) -> None:
    settings = Settings(
        ENVIRONMENT="test",
        MEDIAMTX_JWT_PRIVATE_KEY=_base64_pem(private_key),
        MEDIAMTX_JWT_KEY_ID="from-settings",
    )

    signer = build_mediamtx_jwt_signer(settings)

    assert signer is not None
    token = signer.mint_read_token(stream_path="camera", ttl_seconds=10)
    claims = pyjwt.decode(token, private_key.public_key(), algorithms=["RS256"])
    assert claims["mediamtx_permissions"] == [{"action": "read", "path": "camera"}]
