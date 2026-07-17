"""Tests for opaque token/secret generation and the permission catalog."""

from __future__ import annotations

from app.domains.auth.permissions import (
    DEFAULT_PERMISSIONS,
    DEFAULT_ROLES,
    ROLE_PERMISSIONS,
    permissions_for_roles,
)
from app.domains.auth.tokens import generate_refresh_token, hash_opaque_token, new_jti


def test_new_jti_generates_unique_values() -> None:
    """Each call returns a distinct identifier."""
    assert new_jti() != new_jti()


def test_generate_refresh_token_is_long_and_unique() -> None:
    """Refresh tokens are unique, high-entropy, URL-safe strings."""
    first, second = generate_refresh_token(), generate_refresh_token()
    assert first != second
    assert len(first) > 32


def test_hash_opaque_token_is_deterministic_and_one_way() -> None:
    """The same input always hashes the same way, and the hash isn't the input."""
    token = generate_refresh_token()
    first_hash = hash_opaque_token(token)
    second_hash = hash_opaque_token(token)
    assert first_hash == second_hash
    assert first_hash != token


def test_hash_opaque_token_differs_for_different_inputs() -> None:
    """Different tokens hash to different digests."""
    assert hash_opaque_token("token-a") != hash_opaque_token("token-b")


def test_default_roles_and_permissions_are_named_consistently() -> None:
    """Every seeded role has a resolvable permission set, and names are unique."""
    role_names = [name for name, _ in DEFAULT_ROLES]
    assert len(role_names) == len(set(role_names))
    assert set(role_names) == set(ROLE_PERMISSIONS)

    permission_names = [name for name, _ in DEFAULT_PERMISSIONS]
    assert len(permission_names) == len(set(permission_names))


def test_admin_role_holds_every_catalogued_permission() -> None:
    """The Admin role is granted the full permission catalog, nothing less."""
    all_permissions = frozenset(name for name, _ in DEFAULT_PERMISSIONS)
    assert ROLE_PERMISSIONS["Admin"] == all_permissions


def test_permissions_for_roles_unions_across_multiple_roles() -> None:
    """A principal with two roles receives the union of both roles' permissions."""
    combined = permissions_for_roles(["Viewer", "Agent"])
    assert combined == ROLE_PERMISSIONS["Viewer"] | ROLE_PERMISSIONS["Agent"]


def test_permissions_for_roles_ignores_unknown_role_names() -> None:
    """An unrecognized role name grants nothing instead of raising."""
    assert permissions_for_roles(["NotARealRole"]) == frozenset()
    assert permissions_for_roles([]) == frozenset()
