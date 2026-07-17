"""Tests for structlog configuration and context binding."""

from __future__ import annotations

import structlog

from app.logging.configure import bind_context, clear_context, configure_logging
from app.tests.conftest import make_settings


def test_configure_logging_runs_without_error() -> None:
    """configure_logging can be called with a valid settings object."""
    configure_logging(make_settings(LOG_LEVEL="DEBUG"))


def test_bind_context_only_sets_provided_fields() -> None:
    """bind_context binds only the identifiers explicitly passed."""
    clear_context()
    try:
        bind_context(device_id="device-1", connection_id="conn-1")
        bound = structlog.contextvars.get_contextvars()
        assert bound["device_id"] == "device-1"
        assert bound["connection_id"] == "conn-1"
        assert "message_id" not in bound
    finally:
        clear_context()


def test_bind_context_can_be_called_incrementally() -> None:
    """A later, narrower bind_context call doesn't clobber earlier fields."""
    clear_context()
    try:
        bind_context(connection_id="conn-1")
        bind_context(message_id="msg-1")
        bound = structlog.contextvars.get_contextvars()
        assert bound["connection_id"] == "conn-1"
        assert bound["message_id"] == "msg-1"
    finally:
        clear_context()


def test_clear_context_removes_all_bound_fields() -> None:
    """clear_context wipes everything bound so far."""
    bind_context(trace_id="trace-1")
    clear_context()
    assert structlog.contextvars.get_contextvars() == {}
