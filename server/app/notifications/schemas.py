"""Pydantic request/response contracts for the Notification Framework's REST surface.

This package is small and self-contained (no ``domains/``/``application/``
split, per its own design) — these shapes double as both the API's response
models and the one internal DTO the service layer returns, unlike a full
domain's own ``schemas.py``/``application/dto`` split.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NotificationProviderStatus(BaseModel):
    """One provider's current configuration/health, for the Settings page."""

    provider: str
    enabled: bool
    configured: bool
    last_attempt_at: datetime | None = None
    last_success: bool | None = None
    last_error: str | None = None


class NotificationStatusResponse(BaseModel):
    """Every registered provider's current status."""

    providers: list[NotificationProviderStatus] = Field(default_factory=list)


class TestNotificationResult(BaseModel):
    """The outcome of a Send Test Notification action for one provider.

    Always a 200 response, success or not — testing a notification and
    learning it failed (with why) is an expected outcome, not a server error.
    """

    provider: str
    success: bool
    duration_ms: int
    error_message: str | None = None
