"""Tests for the exponential backoff calculator."""

from __future__ import annotations

import pytest

from app.connection.backoff import ExponentialBackoff


def test_next_delay_doubles_each_attempt() -> None:
    """Delay doubles (the default multiplier) on each successive call."""
    backoff = ExponentialBackoff(base_seconds=1.0, max_seconds=100.0)
    assert backoff.next_delay() == 1.0
    assert backoff.next_delay() == 2.0
    assert backoff.next_delay() == 4.0


def test_next_delay_caps_at_max_seconds() -> None:
    """Delay never exceeds max_seconds."""
    backoff = ExponentialBackoff(base_seconds=10.0, max_seconds=15.0)
    assert backoff.next_delay() == 10.0
    assert backoff.next_delay() == 15.0
    assert backoff.next_delay() == 15.0


def test_reset_returns_to_base_delay() -> None:
    """reset() restarts the attempt counter."""
    backoff = ExponentialBackoff(base_seconds=1.0)
    backoff.next_delay()
    backoff.next_delay()
    backoff.reset()
    assert backoff.next_delay() == 1.0


@pytest.mark.parametrize("base_seconds", [0, -1])
def test_rejects_non_positive_base(base_seconds: float) -> None:
    """base_seconds must be positive."""
    with pytest.raises(ValueError, match="base_seconds"):
        ExponentialBackoff(base_seconds=base_seconds)


def test_rejects_max_seconds_below_base() -> None:
    """max_seconds must be >= base_seconds."""
    with pytest.raises(ValueError, match="max_seconds"):
        ExponentialBackoff(base_seconds=10.0, max_seconds=5.0)


@pytest.mark.parametrize("multiplier", [1, 0.5])
def test_rejects_multiplier_not_greater_than_one(multiplier: float) -> None:
    """multiplier must be greater than 1, or delay would never grow."""
    with pytest.raises(ValueError, match="multiplier"):
        ExponentialBackoff(base_seconds=1.0, multiplier=multiplier)
