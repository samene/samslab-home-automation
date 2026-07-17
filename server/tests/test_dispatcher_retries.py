"""Tests for the pure retry-policy math: exponential backoff and the retry decision."""

from __future__ import annotations

import pytest

from app.dispatcher.retries import compute_backoff_seconds, should_retry


@pytest.mark.parametrize(
    ("retry_count", "expected"),
    [(1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0)],
)
def test_compute_backoff_seconds_doubles_each_attempt(retry_count: int, expected: float) -> None:
    """1s, 2s, 4s, 8s — doubling from a 1s base, per the requested retry policy."""
    assert compute_backoff_seconds(retry_count, base_seconds=1.0, max_seconds=30.0) == expected


def test_compute_backoff_seconds_is_capped_at_the_configured_maximum() -> None:
    """A large retry_count never exceeds the configured ceiling."""
    assert compute_backoff_seconds(10, base_seconds=1.0, max_seconds=8.0) == 8.0


def test_compute_backoff_seconds_never_goes_negative_for_a_zero_retry_count() -> None:
    """A defensive floor: retry_count 0 still returns the base delay, not zero or negative."""
    assert compute_backoff_seconds(0, base_seconds=1.0, max_seconds=30.0) == 1.0


def test_should_retry_allows_up_to_the_configured_maximum() -> None:
    """Retries are allowed strictly below max_retries."""
    assert should_retry(0, max_retries=4) is True
    assert should_retry(3, max_retries=4) is True
    assert should_retry(4, max_retries=4) is False
    assert should_retry(5, max_retries=4) is False


def test_should_retry_with_zero_max_retries_never_retries() -> None:
    """max_retries=0 disables retrying entirely."""
    assert should_retry(0, max_retries=0) is False
