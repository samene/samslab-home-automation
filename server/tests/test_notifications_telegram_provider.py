"""Tests for TelegramProvider: success, retry, exhaustion, and misconfiguration paths.

Uses ``httpx.MockTransport`` (built into httpx, no real network, no extra
dependency) rather than a real Telegram API call — the provider's
``client_factory`` seam exists exactly for this.
"""

from __future__ import annotations

import httpx
import pytest

from app.notifications.config import TelegramConfig
from app.notifications.providers.base import NotificationMessage
from app.notifications.providers.telegram import TelegramProvider

MESSAGE = NotificationMessage(text="hello", event_type="TEST")


def _config(**overrides: object) -> TelegramConfig:
    values: dict[str, object] = {
        "enabled": True,
        "bot_token": "123456:ABC-DEF",
        "chat_id": "42",
        "api_base_url": "https://api.telegram.org",
        "timeout_seconds": 5.0,
        "max_retries": 2,
        "retry_backoff_seconds": 0.001,
    }
    values.update(overrides)
    return TelegramConfig(**values)  # type: ignore[arg-type]


def _provider(handler: object, **config_overrides: object) -> TelegramProvider:
    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]

    return TelegramProvider(_config(**config_overrides), client_factory=client_factory)


async def test_send_succeeds_on_the_first_attempt() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    provider = _provider(handler)
    result = await provider.send(MESSAGE)

    assert result.success is True
    assert result.error_message is None
    assert len(calls) == 1


async def test_send_never_leaks_the_bot_token_into_the_request_log_or_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "123456:ABC-DEF" in str(request.url)  # the real request does carry it
        return httpx.Response(
            400, json={"ok": False, "description": "chat not found: 123456:ABC-DEF"}
        )

    provider = _provider(handler)
    result = await provider.send(MESSAGE)

    assert result.success is False
    assert result.error_message is not None
    assert "123456:ABC-DEF" not in result.error_message
    assert "REDACTED" in result.error_message


async def test_send_does_not_retry_a_client_error() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, json={"ok": False, "description": "bad request"})

    provider = _provider(handler)
    result = await provider.send(MESSAGE)

    assert result.success is False
    assert len(calls) == 1  # a 4xx (non-429) is not retried


async def test_send_retries_a_server_error_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, text="service unavailable")
        return httpx.Response(200, json={"ok": True, "result": {}})

    provider = _provider(handler, max_retries=2)
    result = await provider.send(MESSAGE)

    assert result.success is True
    assert len(calls) == 3


async def test_send_retries_a_rate_limit_response() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={"ok": False, "description": "too many requests"})

    provider = _provider(handler, max_retries=2)
    result = await provider.send(MESSAGE)

    assert result.success is False
    assert len(calls) == 3  # the initial attempt plus both retries


async def test_send_reports_failure_once_all_retries_are_exhausted() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="service unavailable")

    provider = _provider(handler, max_retries=2)
    result = await provider.send(MESSAGE)

    assert result.success is False
    assert result.error_message is not None
    assert len(calls) == 3  # 1 initial attempt + 2 retries
    assert result.duration_seconds >= 0.0


async def test_send_retries_a_network_error_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 2:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler, max_retries=2)
    result = await provider.send(MESSAGE)

    assert result.success is True
    assert len(calls) == 2


async def test_send_never_raises_even_on_a_completely_unexpected_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    provider = _provider(handler)
    result = await provider.send(MESSAGE)  # must not raise

    assert result.success is False
    assert result.error_message is not None


async def test_send_short_circuits_when_disabled() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler, enabled=False)
    result = await provider.send(MESSAGE)

    assert result.success is False
    assert "disabled" in (result.error_message or "")
    assert calls == []  # no network call at all


async def test_send_short_circuits_when_not_configured() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler, bot_token=None)
    result = await provider.send(MESSAGE)

    assert result.success is False
    assert "not configured" in (result.error_message or "")
    assert calls == []


@pytest.mark.parametrize(
    ("enabled", "bot_token", "chat_id", "expected"),
    [
        (True, "token", "42", True),
        (False, "token", "42", False),
        (True, None, "42", False),
        (True, "token", None, False),
    ],
)
def test_is_configured_and_enabled_reflect_config(
    enabled: bool, bot_token: str | None, chat_id: str | None, expected: bool
) -> None:
    config = _config(enabled=enabled, bot_token=bot_token, chat_id=chat_id)
    provider = TelegramProvider(config)
    assert provider.enabled is enabled
    assert provider.is_configured is (bot_token is not None and chat_id is not None)
    assert provider.name == "telegram"


# --- sendPhoto (thumbnail attachment) --------------------------------------


async def test_send_uses_sendphoto_when_photo_bytes_are_present() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    provider = _provider(handler)
    message = NotificationMessage(
        text="✅ Workflow Completed\n\nWorkflow: Morning Garden",
        event_type="WORKFLOW_COMPLETED",
        photo_bytes=b"\xff\xd8jpeg-bytes",
        photo_filename="Morning Garden.jpg",
    )

    result = await provider.send(message)

    assert result.success is True
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path.endswith("/sendPhoto")
    assert not request.url.path.endswith("/sendMessage")
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="chat_id"' in request.content
    assert b'name="caption"' in request.content
    assert b"Morning Garden" in request.content
    assert b'name="photo"' in request.content
    assert b"Morning Garden.jpg" in request.content
    assert b"\xff\xd8jpeg-bytes" in request.content


async def test_send_uses_sendmessage_when_no_photo_bytes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler)

    await provider.send(MESSAGE)

    assert requests[0].url.path.endswith("/sendMessage")


async def test_send_photo_truncates_a_caption_over_telegrams_limit() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler)
    long_text = "x" * 2000
    message = NotificationMessage(
        text=long_text, event_type="TEST", photo_bytes=b"bytes", photo_filename="photo.jpg"
    )

    await provider.send(message)

    # The full 2000-char text must never appear whole in a caption field —
    # only its truncated (<=1024 char) form.
    assert (b"x" * 2000) not in requests[0].content
    assert (b"x" * 1023) in requests[0].content


async def test_send_photo_retries_a_server_error_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 2:
            return httpx.Response(503, text="service unavailable")
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler, max_retries=2)
    message = NotificationMessage(
        text="hi", event_type="TEST", photo_bytes=b"bytes", photo_filename="photo.jpg"
    )

    result = await provider.send(message)

    assert result.success is True
    assert len(calls) == 2
    assert all(call.url.path.endswith("/sendPhoto") for call in calls)
