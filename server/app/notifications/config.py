"""Typed, minimal provider configuration — built once from ``Settings``, never a whole ``Settings`` object smuggled into a provider.

Same convention ``app/api/camera.py``'s dependency function already follows:
pull the specific fields a collaborator needs off ``Settings`` at the
composition root and pass them down explicitly, rather than letting every
provider reach into the app's entire configuration surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Everything ``TelegramProvider`` needs; ``enabled``/``configured`` are checked separately.

    ``enabled`` (the ``TELEGRAM_ENABLED`` switch) is intentionally distinct
    from "bot_token and chat_id are both set" (``is_configured``) — an
    operator can flip notifications off without clearing real credentials.
    """

    enabled: bool
    bot_token: str | None
    chat_id: str | None
    api_base_url: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float

    @property
    def is_configured(self) -> bool:
        """Whether there's actually a bot token and chat id to send with."""
        return bool(self.bot_token) and bool(self.chat_id)


def build_telegram_config(settings: Settings) -> TelegramConfig:
    """Build ``TelegramProvider``'s config from the app's ``Settings``."""
    return TelegramConfig(
        enabled=settings.telegram_enabled,
        bot_token=(
            settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else None
        ),
        chat_id=settings.telegram_chat_id,
        api_base_url=settings.telegram_api_base_url,
        timeout_seconds=settings.telegram_timeout_seconds,
        max_retries=settings.telegram_max_retries,
        retry_backoff_seconds=settings.telegram_retry_backoff_seconds,
    )
