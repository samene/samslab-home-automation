"""Tests for JWT encoding/decoding (transport-independent, no FastAPI involved)."""

from __future__ import annotations

from datetime import timedelta

import jwt as pyjwt
import pytest

from app.domains.auth.exceptions import ExpiredToken, InvalidToken
from app.domains.auth.jwt import JWTCodec


def make_codec(**overrides: object) -> JWTCodec:
    """Build a JWTCodec with sane defaults, overridable per test."""
    kwargs: dict[str, object] = {
        "secret": "a-sufficiently-long-test-signing-secret-value",
        "algorithm": "HS256",
        "issuer": "samslab",
        "audience": "samslab-clients",
        "clock_skew_seconds": 0,
    }
    kwargs.update(overrides)
    return JWTCodec(**kwargs)  # type: ignore[arg-type]


def test_encode_then_decode_round_trips_all_standard_claims() -> None:
    """A token encoded with standard + custom claims decodes back to the same values."""
    codec = make_codec()
    token = codec.encode(
        subject="user-1",
        expires_in=timedelta(minutes=5),
        jti="jti-1",
        claims={"principal_type": "USER", "role": ["Admin"], "permissions": ["devices.read"]},
    )
    payload = codec.decode(token)
    assert payload["sub"] == "user-1"
    assert payload["iss"] == "samslab"
    assert payload["aud"] == "samslab-clients"
    assert payload["jti"] == "jti-1"
    assert payload["role"] == ["Admin"]
    assert payload["permissions"] == ["devices.read"]
    assert payload["principal_type"] == "USER"
    assert "iat" in payload
    assert "exp" in payload


def test_decode_rejects_an_expired_token() -> None:
    """A token whose exp has already passed raises ExpiredToken."""
    codec = make_codec()
    token = codec.encode(subject="user-1", expires_in=timedelta(seconds=-1), jti="jti-1", claims={})
    with pytest.raises(ExpiredToken):
        codec.decode(token)


def test_decode_honors_clock_skew_leeway() -> None:
    """A token expired by less than the configured clock skew is still accepted."""
    codec = make_codec(clock_skew_seconds=30)
    token = codec.encode(subject="user-1", expires_in=timedelta(seconds=-5), jti="jti-1", claims={})
    payload = codec.decode(token)
    assert payload["sub"] == "user-1"


def test_decode_rejects_a_token_signed_with_a_different_secret() -> None:
    """A token whose signature does not match the configured secret is invalid."""
    codec = make_codec()
    other_codec = make_codec(secret="a-completely-different-signing-secret-value")
    token = other_codec.encode(
        subject="user-1", expires_in=timedelta(minutes=5), jti="jti-1", claims={}
    )
    with pytest.raises(InvalidToken):
        codec.decode(token)


def test_decode_rejects_a_token_with_the_wrong_issuer() -> None:
    """A token issued by a different issuer is invalid."""
    codec = make_codec()
    other_issuer_codec = make_codec(issuer="someone-else")
    token = other_issuer_codec.encode(
        subject="user-1", expires_in=timedelta(minutes=5), jti="jti-1", claims={}
    )
    with pytest.raises(InvalidToken):
        codec.decode(token)


def test_decode_rejects_a_token_with_the_wrong_audience() -> None:
    """A token intended for a different audience is invalid."""
    codec = make_codec()
    other_audience_codec = make_codec(audience="someone-elses-clients")
    token = other_audience_codec.encode(
        subject="user-1", expires_in=timedelta(minutes=5), jti="jti-1", claims={}
    )
    with pytest.raises(InvalidToken):
        codec.decode(token)


def test_decode_rejects_a_malformed_token() -> None:
    """A token that isn't valid JWT at all is invalid, not an unhandled exception."""
    codec = make_codec()
    with pytest.raises(InvalidToken):
        codec.decode("not-a-jwt-at-all")


def test_decode_rejects_an_algorithm_confusion_attempt() -> None:
    """A token whose declared algorithm doesn't match the codec's is rejected."""
    codec = make_codec()
    forged = pyjwt.encode(
        {"sub": "user-1", "iss": "samslab", "aud": "samslab-clients"},
        "a-sufficiently-long-test-signing-secret-value",
        algorithm="HS512",
    )
    with pytest.raises(InvalidToken):
        codec.decode(forged)
