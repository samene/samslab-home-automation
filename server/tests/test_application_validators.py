"""Tests for centralized application-layer request validation."""

from __future__ import annotations

import pytest

from app.application.exceptions import ApplicationValidationError
from app.application.validators import PaginationParams, validate_sort_field


def test_pagination_params_accepts_valid_bounds() -> None:
    """A well-formed offset/limit pair is accepted unchanged."""
    params = PaginationParams.create(offset=10, limit=25)
    assert params.offset == 10
    assert params.limit == 25


def test_pagination_params_applies_defaults() -> None:
    """Defaults match the previously-hardcoded controller values."""
    params = PaginationParams.create(offset=0, limit=50)
    assert params.offset == 0
    assert params.limit == 50


@pytest.mark.parametrize(
    "offset,limit",
    [(-1, 50), (0, 0), (0, 101), (-5, 200)],
)
def test_pagination_params_rejects_out_of_bounds_values(offset: int, limit: int) -> None:
    """Negative offsets and out-of-range limits are rejected centrally."""
    with pytest.raises(ApplicationValidationError):
        PaginationParams.create(offset=offset, limit=limit)


def test_validate_sort_field_accepts_ascending_and_descending_allowed_fields() -> None:
    """Both a bare field and its descending ``-field`` form are accepted."""
    allowed = frozenset({"created_at", "priority"})
    assert validate_sort_field("created_at", allowed) == "created_at"
    assert validate_sort_field("-priority", allowed) == "-priority"


def test_validate_sort_field_rejects_a_field_outside_the_allowed_set() -> None:
    """A field not in the use case's allowed set is rejected, with or without a dash."""
    allowed = frozenset({"created_at"})
    with pytest.raises(ApplicationValidationError):
        validate_sort_field("not_a_field", allowed)
    with pytest.raises(ApplicationValidationError):
        validate_sort_field("-not_a_field", allowed)
