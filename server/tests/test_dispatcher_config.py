"""Tests for DispatcherConfig.from_settings."""

from __future__ import annotations

from app.config.settings import Settings
from app.dispatcher.config import DispatcherConfig


def test_from_settings_resolves_every_field_from_the_matching_setting() -> None:
    """Every DispatcherConfig field is sourced from its dispatcher_* settings field."""
    settings = Settings(
        DISPATCHER_POLL_INTERVAL_SECONDS=2.5,
        DISPATCHER_DISCOVERY_BATCH_SIZE=25,
        DISPATCHER_ACK_TIMEOUT_SECONDS=5.5,
        DISPATCHER_EXECUTION_TIMEOUT_SECONDS=120.0,
        DISPATCHER_MAX_RETRIES=6,
        DISPATCHER_RETRY_BACKOFF_BASE_SECONDS=0.5,
        DISPATCHER_RETRY_BACKOFF_MAX_SECONDS=16.0,
        DISPATCHER_SWEEP_INTERVAL_SECONDS=0.25,
    )
    config = DispatcherConfig.from_settings(settings)
    assert config.poll_interval_seconds == 2.5
    assert config.discovery_batch_size == 25
    assert config.ack_timeout_seconds == 5.5
    assert config.execution_timeout_seconds == 120.0
    assert config.max_retries == 6
    assert config.retry_backoff_base_seconds == 0.5
    assert config.retry_backoff_max_seconds == 16.0
    assert config.sweep_interval_seconds == 0.25


def test_from_settings_uses_documented_defaults() -> None:
    """The default settings produce a sane out-of-the-box dispatcher configuration."""
    config = DispatcherConfig.from_settings(Settings())
    assert config.poll_interval_seconds == 1.0
    assert config.discovery_batch_size == 100
    assert config.ack_timeout_seconds == 10.0
    assert config.execution_timeout_seconds == 300.0
    assert config.max_retries == 4
    assert config.retry_backoff_base_seconds == 1.0
    assert config.retry_backoff_max_seconds == 30.0
    assert config.sweep_interval_seconds == 1.0
