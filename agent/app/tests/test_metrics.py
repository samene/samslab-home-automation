"""Tests for the process-global Prometheus metrics.

Every assertion uses a before/after delta since these are module-level
singletons shared across the whole pytest session.
"""

from __future__ import annotations

from app.metrics.registry import (
    AGENT_CONNECTED,
    AGENT_UPTIME_SECONDS,
    CONNECTION_ATTEMPTS_TOTAL,
    HEARTBEAT_FAILURES_TOTAL,
    HEARTBEAT_TOTAL,
    MESSAGES_RECEIVED_TOTAL,
    MESSAGES_SENT_TOTAL,
    RECONNECT_TOTAL,
)


def _value(metric: object) -> float:
    family = next(iter(metric.collect()))  # type: ignore[attr-defined]
    return float(family.samples[0].value)


def test_counters_increment() -> None:
    """Every *_total counter can be incremented."""
    for counter in (
        CONNECTION_ATTEMPTS_TOTAL,
        HEARTBEAT_TOTAL,
        HEARTBEAT_FAILURES_TOTAL,
        RECONNECT_TOTAL,
    ):
        before = _value(counter)
        counter.inc()
        assert _value(counter) == before + 1


def test_agent_connected_gauge_can_be_set() -> None:
    """agent_connected is a 0/1 gauge."""
    AGENT_CONNECTED.set(1)
    assert _value(AGENT_CONNECTED) == 1.0
    AGENT_CONNECTED.set(0)
    assert _value(AGENT_CONNECTED) == 0.0


def test_agent_uptime_gauge_can_be_set() -> None:
    """agent_uptime_seconds is a gauge the lifecycle layer updates periodically."""
    AGENT_UPTIME_SECONDS.set(42.0)
    assert _value(AGENT_UPTIME_SECONDS) == 42.0


def test_message_counters_are_labeled_by_message_type() -> None:
    """messages_sent_total/messages_received_total are labeled by message_type."""
    before = MESSAGES_SENT_TOTAL.labels(message_type="PING")._value.get()
    MESSAGES_SENT_TOTAL.labels(message_type="PING").inc()
    assert MESSAGES_SENT_TOTAL.labels(message_type="PING")._value.get() == before + 1

    before_received = MESSAGES_RECEIVED_TOTAL.labels(message_type="PONG")._value.get()
    MESSAGES_RECEIVED_TOTAL.labels(message_type="PONG").inc()
    assert MESSAGES_RECEIVED_TOTAL.labels(message_type="PONG")._value.get() == before_received + 1
