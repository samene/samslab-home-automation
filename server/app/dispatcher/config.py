"""Immutable dispatcher tuning, built once from application ``Settings``."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings


@dataclass(frozen=True, slots=True)
class DispatcherConfig:
    """All dispatcher timing/retry knobs, resolved once at startup."""

    poll_interval_seconds: float
    discovery_batch_size: int
    ack_timeout_seconds: float
    execution_timeout_seconds: float
    max_retries: int
    retry_backoff_base_seconds: float
    retry_backoff_max_seconds: float
    sweep_interval_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> DispatcherConfig:
        """Build a config snapshot from the process-wide settings object."""
        return cls(
            poll_interval_seconds=settings.dispatcher_poll_interval_seconds,
            discovery_batch_size=settings.dispatcher_discovery_batch_size,
            ack_timeout_seconds=settings.dispatcher_ack_timeout_seconds,
            execution_timeout_seconds=settings.dispatcher_execution_timeout_seconds,
            max_retries=settings.dispatcher_max_retries,
            retry_backoff_base_seconds=settings.dispatcher_retry_backoff_base_seconds,
            retry_backoff_max_seconds=settings.dispatcher_retry_backoff_max_seconds,
            sweep_interval_seconds=settings.dispatcher_sweep_interval_seconds,
        )
