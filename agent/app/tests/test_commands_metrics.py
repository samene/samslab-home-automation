"""Tests for the command runtime's Prometheus metrics.

Every assertion uses a before/after delta since these are module-level
singletons shared across the whole pytest session.
"""

from __future__ import annotations

from typing import Any

from app.commands.metrics import (
    COMMAND_EXECUTION_DURATION_SECONDS,
    COMMANDS_COMPLETED_TOTAL,
    COMMANDS_FAILED_TOTAL,
    COMMANDS_RECEIVED_TOTAL,
    COMMANDS_TIMEOUT_TOTAL,
    REGISTERED_HANDLERS,
    RUNNING_COMMANDS,
)


def _value(metric: Any, **labels: str) -> float:
    target = metric.labels(**labels) if labels else metric
    family = next(iter(target.collect()))
    return float(family.samples[0].value)


def test_received_completed_failed_timeout_counters_are_labeled_by_command_type() -> None:
    """Every *_total counter accepts a command_type label and can be incremented."""
    for counter in (
        COMMANDS_RECEIVED_TOTAL,
        COMMANDS_COMPLETED_TOTAL,
        COMMANDS_FAILED_TOTAL,
        COMMANDS_TIMEOUT_TOTAL,
    ):
        before = _value(counter, command_type="test.metrics")
        counter.labels(command_type="test.metrics").inc()
        assert _value(counter, command_type="test.metrics") == before + 1


def test_execution_duration_histogram_observes_by_command_type() -> None:
    """The duration histogram accepts observations labeled by command_type."""
    COMMAND_EXECUTION_DURATION_SECONDS.labels(command_type="test.metrics").observe(0.01)


def test_registered_handlers_gauge_can_be_set() -> None:
    """registered_handlers is a plain gauge."""
    REGISTERED_HANDLERS.set(3)
    assert _value(REGISTERED_HANDLERS) == 3.0


def test_running_commands_gauge_can_be_set() -> None:
    """running_commands is a plain gauge."""
    RUNNING_COMMANDS.set(2)
    assert _value(RUNNING_COMMANDS) == 2.0
    RUNNING_COMMANDS.set(0)
