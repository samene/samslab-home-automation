"""Shared pytest fixtures for the agent test suite."""

from __future__ import annotations

from typing import Any

import pytest

from app.config.settings import AgentSettings


def make_settings(**overrides: Any) -> AgentSettings:
    """Build a valid ``AgentSettings`` without touching the real environment or ``.env``."""
    values: dict[str, Any] = {
        "SERVER_URL": "ws://localhost:8000/ws",
        "DEVICE_NAME": "test-device",
        "DEVICE_CLIENT_ID": "test-client-id",
        "DEVICE_PRIVATE_KEY": "test-private-key",
        "AUTH_TOKEN_URL": "http://localhost:8000/auth/device/token",
        "LOCAL_DATA_DIRECTORY": "/tmp/samslab-agent-test/data",
        "CACHE_DIRECTORY": "/tmp/samslab-agent-test/cache",
        "TMP_DIRECTORY": "/tmp/samslab-agent-test/tmp",
    }
    values.update(overrides)
    return AgentSettings(_env_file=None, **values)


@pytest.fixture
def settings() -> AgentSettings:
    """A valid, isolated ``AgentSettings`` instance for tests that don't need overrides."""
    return make_settings()
