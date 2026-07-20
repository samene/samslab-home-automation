"""Runs a real Sam's Lab cloud server — a real TCP socket, a real SQLite database.

Deliberately not ``TestClient``: a ``FakeAgent`` (``tests/fakes/fake_agent.py``)
connects over an actual ``websockets`` client, which needs an actual
``ws://host:port/path`` to dial — there is no in-process transport a
standalone WebSocket client library can attach to. Running a real
``uvicorn.Server`` inside the test's own event loop keeps this fast (no
subprocess, no IPC) while still exercising the real ASGI app, the real
lifespan (which starts/stops the real ``CommandDispatcher``), and a real
socket end to end. See ``docs/development/INTEGRATION_TESTING.md``.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI

from app.config.settings import Environment, Settings
from app.core.container import ApplicationContainer
from app.core.database import Database
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.permissions import permissions_for_roles
from app.domains.auth.tokens import new_jti
from app.main import create_app

#: A fixed, sufficiently long test-only signing secret — never a real credential.
JWT_TEST_SECRET = "integration-test-signing-secret-value-not-for-production-use"


def _free_port() -> int:
    """Ask the OS for an unused TCP port so parallel test runs never collide."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def default_test_settings(*, database_url: str, **overrides: Any) -> Settings:
    """Fast, deterministic settings shared by integration/e2e/load tests.

    Every timing value is tuned short so tests run quickly without being so
    short that real network/asyncio scheduling jitter causes flakiness.
    ``database_url`` has no default — every caller must supply its own fresh
    file so tests never share persisted state.
    """
    values: dict[str, Any] = {
        "SERVER_NAME": "Sam's Lab Integration Test Server",
        "ENVIRONMENT": Environment.TEST,
        "JWT_SECRET": JWT_TEST_SECRET,
        "DATABASE_URL": database_url,
        "WS_HEARTBEAT_INTERVAL_SECONDS": 30.0,
        "WS_HEARTBEAT_TIMEOUT_SECONDS": 10.0,
        "WS_IDLE_TIMEOUT_SECONDS": 90.0,
        "WS_HELLO_TIMEOUT_SECONDS": 5.0,
        "WS_OUTGOING_QUEUE_SIZE": 50,
        "WS_MESSAGE_ACK_TIMEOUT_SECONDS": 2.0,
        "WS_MESSAGE_ACK_MAX_RETRIES": 2,
        "DISPATCHER_POLL_INTERVAL_SECONDS": 0.05,
        "DISPATCHER_SWEEP_INTERVAL_SECONDS": 0.05,
        "DISPATCHER_ACK_TIMEOUT_SECONDS": 2.0,
        "DISPATCHER_EXECUTION_TIMEOUT_SECONDS": 2.0,
        "DISPATCHER_MAX_RETRIES": 2,
        "DISPATCHER_RETRY_BACKOFF_BASE_SECONDS": 0.05,
        "DISPATCHER_RETRY_BACKOFF_MAX_SECONDS": 0.2,
    }
    values.update(overrides)
    return Settings(**values)


@dataclass
class ServerHarness:
    """A real, running Sam's Lab server plus everything needed to drive it in tests."""

    app: FastAPI
    settings: Settings
    base_url: str
    ws_url: str
    http: httpx.AsyncClient
    jwt_codec: JWTCodec
    server: uvicorn.Server
    serve_task: asyncio.Task[None]

    @property
    def container(self) -> ApplicationContainer:
        """The application's own dependency-injector container."""
        return self.app.state.container  # type: ignore[no-any-return]

    @property
    def database(self) -> Database:
        """The real ``Database`` instance backing this running server."""
        result: Database = self.container.database()
        return result

    def issue_device_token(
        self,
        device_id: UUID,
        *,
        expires_in: timedelta | None = None,
        roles: list[str] | None = None,
    ) -> str:
        """Issue a real, signed device (agent) JWT — the same shape the Auth domain issues."""
        roles = roles or ["Agent"]
        return self.jwt_codec.encode(
            subject=str(device_id),
            expires_in=expires_in or timedelta(minutes=5),
            jti=new_jti(),
            claims={
                "principal_type": "DEVICE",
                "role": roles,
                "permissions": sorted(permissions_for_roles(roles)),
                "device_id": str(device_id),
            },
        )

    def issue_user_token(
        self, *, roles: list[str] | None = None, expires_in: timedelta | None = None
    ) -> str:
        """Issue a real, signed human-user JWT (defaults to the Admin role)."""
        roles = roles or ["Admin"]
        return self.jwt_codec.encode(
            subject=str(uuid4()),
            expires_in=expires_in or timedelta(minutes=5),
            jti=new_jti(),
            claims={
                "principal_type": "USER",
                "role": roles,
                "permissions": sorted(permissions_for_roles(roles)),
            },
        )

    @staticmethod
    def auth_headers(token: str) -> dict[str, str]:
        """The standard bearer-token header for an authenticated REST call."""
        return {"Authorization": f"Bearer {token}"}

    async def register_device(
        self,
        *,
        device_name: str | None = None,
        display_name: str = "Integration Test Device",
        capabilities: list[dict[str, Any]] | None = None,
    ) -> UUID:
        """Register a device through the real REST API (``POST /devices``)."""
        name = device_name or f"agent-{uuid4().hex[:8]}"
        response = await self.http.post(
            "/devices",
            json={
                "device_name": name,
                "hostname": f"{name}.local",
                "display_name": display_name,
                "capabilities": capabilities or [],
            },
        )
        response.raise_for_status()
        return UUID(response.json()["id"])

    async def create_command(
        self,
        device_id: UUID,
        command_type: str,
        *,
        payload: dict[str, Any] | None = None,
        priority: str = "NORMAL",
        max_retries: int = 0,
        expires_at: str | None = None,
    ) -> UUID:
        """Create a command through the real REST API (``POST /commands``)."""
        body: dict[str, Any] = {
            "device_id": str(device_id),
            "command_type": command_type,
            "payload": payload or {},
            "priority": priority,
            "max_retries": max_retries,
        }
        if expires_at is not None:
            body["expires_at"] = expires_at
        response = await self.http.post("/commands", json=body)
        response.raise_for_status()
        return UUID(response.json()["id"])

    async def get_command(self, command_id: UUID) -> dict[str, Any]:
        """Fetch one command's full detail (status, result, event trail) via REST."""
        response = await self.http.get(f"/commands/{command_id}")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def get_device(self, device_id: UUID) -> dict[str, Any]:
        """Fetch one device's current state via REST."""
        response = await self.http.get(f"/devices/{device_id}")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def metrics_text(self) -> str:
        """The raw Prometheus text-exposition body from ``GET /metrics``."""
        response = await self.http.get("/metrics")
        response.raise_for_status()
        return response.text

    async def dispatcher_status(self, admin_token: str) -> dict[str, Any]:
        """The dispatcher's own run-state snapshot (``GET /dispatcher/status``)."""
        response = await self.http.get("/dispatcher/status", headers=self.auth_headers(admin_token))
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def dispatcher_queue(self, admin_token: str) -> list[dict[str, Any]]:
        """The dispatcher's in-memory queue snapshot (``GET /dispatcher/queue``)."""
        response = await self.http.get("/dispatcher/queue", headers=self.auth_headers(admin_token))
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    async def dispatcher_running(self, admin_token: str) -> list[dict[str, Any]]:
        """Commands past dispatch, awaiting ack or a result (``GET /dispatcher/running``)."""
        response = await self.http.get(
            "/dispatcher/running", headers=self.auth_headers(admin_token)
        )
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    async def dispatcher_statistics(self, admin_token: str) -> dict[str, Any]:
        """The dispatcher's operational counters (``GET /dispatcher/statistics``)."""
        response = await self.http.get(
            "/dispatcher/statistics", headers=self.auth_headers(admin_token)
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def sessions(self, admin_token: str) -> list[dict[str, Any]]:
        """Every currently connected device session (``GET /ws/sessions``)."""
        response = await self.http.get(
            f"{self.settings.websocket_path}/sessions", headers=self.auth_headers(admin_token)
        )
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    async def session_for(self, admin_token: str, device_id: UUID) -> dict[str, Any] | None:
        """One device's current session, or ``None`` if it isn't connected."""
        response = await self.http.get(
            f"{self.settings.websocket_path}/sessions/{device_id}",
            headers=self.auth_headers(admin_token),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def health(self) -> dict[str, Any]:
        """The unauthenticated ``GET /health`` liveness check."""
        response = await self.http.get("/health")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def readiness(self) -> httpx.Response:
        """The unauthenticated ``GET /ready`` readiness check (raw response — status may be 503)."""
        return await self.http.get("/ready")

    async def stop(self) -> None:
        """Shut the server down cleanly; the app's own lifespan disposes the database."""
        await self.http.aclose()
        self.server.should_exit = True
        await self.serve_task


@asynccontextmanager
async def run_server(settings: Settings) -> AsyncIterator[ServerHarness]:
    """Start a real Sam's Lab server on a real TCP port; stop it on exit.

    Schema creation happens here, before uvicorn's lifespan starts the
    dispatcher, so every test has working tables immediately.
    """
    app = create_app(settings)
    database: Database = app.state.container.database()
    if database is None:
        raise RuntimeError("settings.database_url must be set for the integration harness")
    await database.create_schema_for_testing()

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    base_url = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}{settings.websocket_path}"
    jwt_codec = JWTCodec(
        secret=settings.jwt_secret.get_secret_value(),  # type: ignore[union-attr]
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        clock_skew_seconds=settings.jwt_clock_skew_seconds,
    )
    http_client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    harness = ServerHarness(
        app=app,
        settings=settings,
        base_url=base_url,
        ws_url=ws_url,
        http=http_client,
        jwt_codec=jwt_codec,
        server=server,
        serve_task=serve_task,
    )
    try:
        yield harness
    finally:
        await harness.stop()
