"""Tests for Argon2 password hashing."""

from __future__ import annotations

from app.domains.auth.passwords import hash_password, verify_password


def test_hash_password_never_returns_the_plaintext() -> None:
    """The stored hash never contains the plaintext password verbatim."""
    password_hash = hash_password("correct-horse-battery-staple")
    assert "correct-horse-battery-staple" not in password_hash
    assert password_hash.startswith("$argon2")


def test_verify_password_accepts_the_correct_password() -> None:
    """Verification succeeds for the exact password that was hashed."""
    password_hash = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", password_hash) is True


def test_verify_password_rejects_an_incorrect_password() -> None:
    """Verification fails for any other password, without raising."""
    password_hash = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", password_hash) is False


def test_verify_password_rejects_a_malformed_hash_without_raising() -> None:
    """An invalid/foreign hash format fails verification rather than raising."""
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_hash_password_salts_each_call_differently() -> None:
    """Hashing the same password twice produces different hashes (random salt)."""
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second
    assert verify_password("same-password", first) is True
    assert verify_password("same-password", second) is True
