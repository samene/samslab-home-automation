"""Tests for AgentSettings environment parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import load_settings
from app.tests.conftest import make_settings


def test_settings_load_required_fields() -> None:
    """Required fields resolve from explicit constructor values."""
    settings = make_settings()

    assert settings.server_url == "ws://localhost:8000/ws"
    assert settings.device_name == "test-device"
    assert settings.device_client_id == "test-client-id"
    assert settings.device_private_key.get_secret_value() == "test-private-key"
    assert settings.auth_token_url == "http://localhost:8000/auth/device/token"


def test_settings_defaults() -> None:
    """Optional fields fall back to documented defaults."""
    settings = make_settings()

    assert settings.log_level == "INFO"
    assert settings.heartbeat_interval == 30.0
    assert settings.reconnect_interval == 5.0
    assert settings.protocol_version == 1
    assert settings.device_display_name is None
    assert settings.device_description is None


def test_settings_reject_missing_server_url() -> None:
    """SERVER_URL is required."""
    with pytest.raises(ValidationError):
        make_settings(SERVER_URL=None)


def test_settings_reject_non_websocket_server_url() -> None:
    """SERVER_URL must be a ws:// or wss:// URL."""
    with pytest.raises(ValidationError, match="SERVER_URL"):
        make_settings(SERVER_URL="http://localhost:8000")


def test_settings_accepts_wss_url() -> None:
    """A secure WebSocket URL is accepted."""
    settings = make_settings(SERVER_URL="wss://cloud.example/ws")
    assert settings.server_url == "wss://cloud.example/ws"


def test_settings_reject_empty_device_name() -> None:
    """DEVICE_NAME must not be blank."""
    with pytest.raises(ValidationError, match="DEVICE_NAME"):
        make_settings(DEVICE_NAME="   ")


def test_settings_reject_empty_device_client_id() -> None:
    """DEVICE_CLIENT_ID must not be blank."""
    with pytest.raises(ValidationError, match="DEVICE_CLIENT_ID"):
        make_settings(DEVICE_CLIENT_ID="   ")


def test_settings_reject_empty_device_private_key() -> None:
    """DEVICE_PRIVATE_KEY must not be blank."""
    with pytest.raises(ValidationError, match="DEVICE_PRIVATE_KEY"):
        make_settings(DEVICE_PRIVATE_KEY="   ")


def test_settings_reject_non_http_auth_token_url() -> None:
    """AUTH_TOKEN_URL must be an http(s) URL."""
    with pytest.raises(ValidationError, match="AUTH_TOKEN_URL"):
        make_settings(AUTH_TOKEN_URL="ftp://example.com/token")


def test_settings_normalizes_log_level() -> None:
    """LOG_LEVEL is upper-cased and stripped."""
    settings = make_settings(LOG_LEVEL="  debug ")
    assert settings.log_level == "DEBUG"


def test_settings_reject_empty_log_level() -> None:
    """An empty LOG_LEVEL is rejected rather than silently defaulting."""
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        make_settings(LOG_LEVEL="   ")


def test_settings_directories_are_paths() -> None:
    """Directory settings parse into ``Path`` objects."""
    settings = make_settings(LOCAL_DATA_DIRECTORY="/var/lib/samslab-agent")
    assert settings.local_data_directory == Path("/var/lib/samslab-agent")


def test_load_settings_applies_overrides() -> None:
    """load_settings' overrides take priority, matching 'CLI beats environment'."""
    settings = load_settings(
        {
            "SERVER_URL": "ws://localhost:8000/ws",
            "DEVICE_NAME": "override-device",
            "DEVICE_CLIENT_ID": "override-client-id",
            "DEVICE_PRIVATE_KEY": "override-private-key",
            "AUTH_TOKEN_URL": "http://localhost:8000/auth/device/token",
        }
    )
    assert settings.device_name == "override-device"


def test_load_settings_with_no_overrides_requires_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no overrides, load_settings falls through to the environment."""
    monkeypatch.setenv("SERVER_URL", "ws://env.example/ws")
    monkeypatch.setenv("DEVICE_NAME", "env-device")
    monkeypatch.setenv("DEVICE_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("DEVICE_PRIVATE_KEY", "env-private-key")
    monkeypatch.setenv("AUTH_TOKEN_URL", "http://localhost:8000/auth/device/token")
    monkeypatch.delenv("DEVICE_DISPLAY_NAME", raising=False)

    settings = load_settings()

    assert settings.server_url == "ws://env.example/ws"
    assert settings.device_name == "env-device"


def test_pump_settings_defaults() -> None:
    """PUMP_* fields default to a safe, active-high 200ms pulse on GPIO17."""
    settings = make_settings()

    assert settings.pump_gpio_pin == 17
    assert settings.pump_active_high is True
    assert settings.pump_trigger_pulse_ms == 200
    assert settings.pump_trigger_pulse_min_ms == 50
    assert settings.pump_trigger_pulse_max_ms == 5000


def test_pump_settings_are_overridable() -> None:
    """Every pump setting is configurable via environment variables."""
    settings = make_settings(
        PUMP_GPIO_PIN=22,
        PUMP_ACTIVE_HIGH=False,
        PUMP_TRIGGER_PULSE_MS=300,
        PUMP_TRIGGER_PULSE_MIN_MS=100,
        PUMP_TRIGGER_PULSE_MAX_MS=1000,
    )

    assert settings.pump_gpio_pin == 22
    assert settings.pump_active_high is False
    assert settings.pump_trigger_pulse_ms == 300
    assert settings.pump_trigger_pulse_min_ms == 100
    assert settings.pump_trigger_pulse_max_ms == 1000


def test_pump_settings_reject_pulse_ms_outside_its_own_bounds() -> None:
    """The default pulse must itself fall within [min, max] — fail fast at startup."""
    with pytest.raises(ValidationError, match="PUMP_TRIGGER_PULSE_MS"):
        make_settings(
            PUMP_TRIGGER_PULSE_MS=10,
            PUMP_TRIGGER_PULSE_MIN_MS=50,
            PUMP_TRIGGER_PULSE_MAX_MS=5000,
        )


def test_pump_settings_reject_min_greater_than_max() -> None:
    """An inverted pulse range is rejected rather than silently misbehaving."""
    with pytest.raises(ValidationError, match="PUMP_TRIGGER_PULSE_MIN_MS"):
        make_settings(PUMP_TRIGGER_PULSE_MIN_MS=1000, PUMP_TRIGGER_PULSE_MAX_MS=500)
