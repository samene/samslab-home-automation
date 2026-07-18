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


def test_settings_treat_empty_aws_fields_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty-string AWS_* environment value parses to None, not an empty string."""
    monkeypatch.setenv("AWS_REGION", "")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "")
    monkeypatch.setenv("AWS_S3_BUCKET", "")

    settings = Settings()

    assert settings.aws_region is None
    assert settings.aws_access_key_id is None
    assert settings.aws_secret_access_key is None
    assert settings.aws_s3_bucket is None


def test_settings_load_configured_aws_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty AWS_* environment value is preserved rather than coerced away."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_S3_BUCKET", "samslab-snapshots")

    settings = Settings()

    assert settings.aws_region == "us-east-1"
    assert settings.aws_access_key_id == "AKIAEXAMPLE"
    assert settings.aws_secret_access_key is not None
    assert settings.aws_secret_access_key.get_secret_value() == "secret"
    assert settings.aws_s3_bucket == "samslab-snapshots"
