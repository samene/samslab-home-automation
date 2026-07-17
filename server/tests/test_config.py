"""Tests for Pydantic Settings environment parsing and validation."""

import pytest
from pydantic import ValidationError

from app.config.settings import Environment, Settings


def test_settings_load_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings accept documented environment names and parse origin lists."""
    monkeypatch.setenv("SERVER_NAME", "Configured Server")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("ALLOW_ORIGINS", "https://one.example, https://two.example")

    settings = Settings()

    assert settings.server_name == "Configured Server"
    assert settings.environment is Environment.PRODUCTION
    assert settings.port == 9000
    assert settings.allow_origins == ("https://one.example", "https://two.example")


def test_settings_reject_invalid_websocket_path() -> None:
    """A future protocol path must remain an absolute URL path."""
    with pytest.raises(ValidationError, match="WEBSOCKET_PATH"):
        Settings(WEBSOCKET_PATH="ws")
