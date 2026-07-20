"""The only implemented notification provider for V1: the Telegram Bot API.

Uses ``sendMessage`` (https://core.telegram.org/bots/api#sendmessage) over
plain HTTPS — no long-lived connection, no webhook, nothing else registered
with Telegram. A failure here is always reported as a ``NotificationResult``,
never raised, and the bot token never appears in a log line or an error
message returned to a caller.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

import httpx
import structlog

from app.notifications.config import TelegramConfig
from app.notifications.metrics import (
    TELEGRAM_NOTIFICATION_DURATION_SECONDS,
    TELEGRAM_NOTIFICATIONS_TOTAL,
)
from app.notifications.providers.base import NotificationMessage, NotificationResult

logger = structlog.get_logger(__name__)

_REDACTED = "***REDACTED***"
# Telegram's own limit for a sendPhoto caption (sendMessage's plain text
# limit is 4096, comfortably larger than anything this codebase's own
# message formatting ever produces).
_CAPTION_LIMIT = 1024


def _redact(text: str, bot_token: str | None) -> str:
    """Strip a bot token out of Telegram's own error text before it's logged or stored."""
    if not bot_token:
        return text
    return text.replace(bot_token, _REDACTED)


def _truncate_caption(text: str) -> str:
    """Defensively cap a sendPhoto caption at Telegram's 1024-character limit."""
    if len(text) <= _CAPTION_LIMIT:
        return text
    return text[: _CAPTION_LIMIT - 1] + "…"


class TelegramProvider:
    """Sends already-formatted text to one configured Telegram chat."""

    def __init__(
        self,
        config: TelegramConfig,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        """``client_factory`` is a test seam — production never overrides it.

        Building a fresh ``httpx.AsyncClient`` per ``send()`` call (rather
        than holding one open for the provider's lifetime) keeps this
        provider trivially safe to construct once at startup and call
        concurrently, with no shared-connection-pool lifecycle to manage.
        """
        self._config = config
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self._config.timeout_seconds)
        )

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def is_configured(self) -> bool:
        return self._config.is_configured

    async def send(self, message: NotificationMessage) -> NotificationResult:
        """Never raises: the outer try/except is the ultimate safety net on top of the retry loop's own."""
        if not self._config.enabled:
            return NotificationResult(
                success=False,
                duration_seconds=0.0,
                error_message="Telegram notifications are disabled",
            )
        if not self.is_configured:
            return NotificationResult(
                success=False,
                duration_seconds=0.0,
                error_message="Telegram is not configured (missing bot token or chat id)",
            )
        try:
            return await self._send_with_retry(message)
        except (
            Exception
        ) as error:  # pragma: no cover - defensive; _send_with_retry already handles httpx errors
            logger.warning("telegram_notification_unexpected_error", error=str(error))
            return NotificationResult(
                success=False, duration_seconds=0.0, error_message=f"Unexpected error: {error}"
            )

    async def _send_with_retry(self, message: NotificationMessage) -> NotificationResult:
        url, request_kwargs = self._build_request(message)
        attempts = self._config.max_retries + 1
        started = time.monotonic()
        last_error = "unknown error"

        async with self._client_factory() as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(url, **request_kwargs)
                except httpx.HTTPError as error:
                    last_error = f"{type(error).__name__}: {error}"
                else:
                    ok = False
                    with contextlib.suppress(Exception):
                        ok = bool(response.json().get("ok"))
                    if response.status_code == 200 and ok:
                        duration = time.monotonic() - started
                        self._record(
                            success=True,
                            duration=duration,
                            event_type=message.event_type,
                            attempts=attempt + 1,
                        )
                        return NotificationResult(success=True, duration_seconds=duration)
                    last_error = _redact(
                        f"Telegram API returned {response.status_code}: {response.text}",
                        self._config.bot_token,
                    )
                    # 4xx (other than a rate limit) means the request itself
                    # is wrong — a bad token, an unreachable chat id, a
                    # malformed request — and retrying identically will
                    # never succeed, so stop immediately rather than burn
                    # through every retry for nothing.
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        break
                if attempt < attempts - 1:
                    await asyncio.sleep(self._config.retry_backoff_seconds * (2**attempt))

        duration = time.monotonic() - started
        self._record(
            success=False, duration=duration, event_type=message.event_type, attempts=attempts
        )
        return NotificationResult(
            success=False, duration_seconds=duration, error_message=last_error
        )

    def _build_request(self, message: NotificationMessage) -> tuple[str, dict[str, Any]]:
        """``sendPhoto`` (with the text as a caption) when a thumbnail is attached, ``sendMessage`` otherwise.

        No S3 presigned URL is ever involved: ``message.photo_bytes`` is
        already-fetched raw image bytes (see
        ``NotificationService._resolve_photo_bytes``), uploaded to Telegram
        directly as multipart form data — Telegram never fetches from S3 at
        all, and no S3 URL (signed or otherwise) is ever generated or sent.
        """
        base = f"{self._config.api_base_url}/bot{self._config.bot_token}"
        if message.photo_bytes is not None:
            return (
                f"{base}/sendPhoto",
                {
                    "data": {
                        "chat_id": self._config.chat_id,
                        "caption": _truncate_caption(message.text),
                    },
                    "files": {
                        "photo": (
                            message.photo_filename or "photo.jpg",
                            message.photo_bytes,
                            "image/jpeg",
                        )
                    },
                },
            )
        return (
            f"{base}/sendMessage",
            {"json": {"chat_id": self._config.chat_id, "text": message.text}},
        )

    def _record(self, *, success: bool, duration: float, event_type: str, attempts: int) -> None:
        TELEGRAM_NOTIFICATIONS_TOTAL.inc()
        TELEGRAM_NOTIFICATION_DURATION_SECONDS.observe(duration)
        log = logger.info if success else logger.warning
        log(
            "telegram_notification_sent" if success else "telegram_notification_failed",
            event_type=event_type,
            attempts=attempts,
            duration_seconds=round(duration, 3),
        )
