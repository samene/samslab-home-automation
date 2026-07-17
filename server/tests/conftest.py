"""Shared fixtures for isolated server-foundation tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.config.settings import Environment, Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Provide deterministic test settings without environment dependencies."""
    return Settings(
        SERVER_NAME="Sam's Lab Test Server",
        ENVIRONMENT=Environment.TEST,
        LOG_LEVEL="INFO",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Create a new application instance for each test."""
    return create_app(settings)
