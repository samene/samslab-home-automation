"""Tests for fetch_device_token: assertion signing and the token-exchange HTTP call."""

from __future__ import annotations

import base64

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.connection.exceptions import DeviceTokenRequestError
from app.connection.token_provider import fetch_device_token
from app.tests.conftest import make_settings


def _response(status_code: int, json_body: dict[str, object]) -> httpx.Response:
    """A response with a request attached, so raise_for_status() works like a real one."""
    request = httpx.Request("POST", "http://server.local/auth/device/token")
    return httpx.Response(status_code, json=json_body, request=request)


def _private_key_b64() -> tuple[rsa.RSAPrivateKey, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_key, base64.b64encode(pem).decode("ascii")


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient, intercepting the one POST call made."""

    last_request: dict[str, object] | None = None

    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error

    def __call__(self, *args: object, **kwargs: object) -> _FakeAsyncClient:
        return self

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, object]) -> httpx.Response:
        _FakeAsyncClient.last_request = {"url": url, "json": json}
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


@pytest.mark.asyncio
async def test_fetch_device_token_signs_an_assertion_and_returns_the_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, private_key_b64 = _private_key_b64()
    settings = make_settings(
        DEVICE_CLIENT_ID="device-1",
        DEVICE_PRIVATE_KEY=private_key_b64,
        AUTH_TOKEN_URL="http://server.local/auth/device/token",
    )
    response = _response(200, {"access_token": "fresh-token", "token_type": "bearer"})
    fake_client = _FakeAsyncClient(response=response)
    monkeypatch.setattr("app.connection.token_provider.httpx.AsyncClient", fake_client)

    token = await fetch_device_token(settings)

    assert token == "fresh-token"
    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["url"] == "http://server.local/auth/device/token"
    body = request["json"]
    assert isinstance(body, dict)
    assert body["client_id"] == "device-1"

    claims = pyjwt.decode(body["assertion"], private_key.public_key(), algorithms=["RS256"])
    assert claims["sub"] == "device-1"


@pytest.mark.asyncio
async def test_fetch_device_token_raises_on_a_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, private_key_b64 = _private_key_b64()
    settings = make_settings(DEVICE_PRIVATE_KEY=private_key_b64)
    response = _response(401, {"detail": "invalid assertion"})
    fake_client = _FakeAsyncClient(response=response)
    monkeypatch.setattr("app.connection.token_provider.httpx.AsyncClient", fake_client)

    with pytest.raises(DeviceTokenRequestError):
        await fetch_device_token(settings)


@pytest.mark.asyncio
async def test_fetch_device_token_raises_on_a_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, private_key_b64 = _private_key_b64()
    settings = make_settings(DEVICE_PRIVATE_KEY=private_key_b64)
    fake_client = _FakeAsyncClient(error=httpx.ConnectError("connection refused"))
    monkeypatch.setattr("app.connection.token_provider.httpx.AsyncClient", fake_client)

    with pytest.raises(DeviceTokenRequestError):
        await fetch_device_token(settings)


@pytest.mark.asyncio
async def test_fetch_device_token_raises_when_access_token_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, private_key_b64 = _private_key_b64()
    settings = make_settings(DEVICE_PRIVATE_KEY=private_key_b64)
    response = _response(200, {"token_type": "bearer"})
    fake_client = _FakeAsyncClient(response=response)
    monkeypatch.setattr("app.connection.token_provider.httpx.AsyncClient", fake_client)

    with pytest.raises(DeviceTokenRequestError):
        await fetch_device_token(settings)


@pytest.mark.asyncio
async def test_fetch_device_token_raises_for_a_non_rsa_private_key() -> None:
    """A DEVICE_PRIVATE_KEY that doesn't decode to an RSA key fails fast, before any HTTP call."""
    garbage_b64 = base64.b64encode(b"not a real PEM key").decode("ascii")
    settings = make_settings(DEVICE_PRIVATE_KEY=garbage_b64)

    with pytest.raises(DeviceTokenRequestError):
        await fetch_device_token(settings)
