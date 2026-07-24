"""FastAPI delivery adapter for the browser-facing terminal WebSocket.

Transport only, exactly like ``app/websocket/gateway.py`` — the one
cross-domain call here is ``DeviceApplicationService`` (confirming the
target device exists and is enabled, the same Application Layer seam REST
and the agent gateway both use). Relaying to the agent goes through the
existing agent ``SessionManager.send`` — never a second WebSocket client,
never a new agent-facing transport.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.application.events.bus import EventBus
from app.application.exceptions import ApplicationError
from app.application.services.device_service import DeviceApplicationService
from app.config.settings import Settings
from app.core.database import Database
from app.domains.auth.exceptions import AuthDomainError
from app.domains.auth.jwt import JWTCodec
from app.domains.auth.schemas import Principal, PrincipalType
from app.domains.auth.service import decode_principal
from app.domains.devices.models import DeviceStatus
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.service import DeviceService
from app.terminal.connection import BackpressureExceededError, BrowserConnection
from app.terminal.exceptions import (
    AuthenticationFailedError,
    DeviceUnavailableError,
    HandshakeTimeoutError,
    ProtocolViolationError,
)
from app.terminal.manager import TerminalSessionManager
from app.websocket.constants import CloseCode
from app.websocket.exceptions import ProtocolViolationError as WireProtocolViolationError
from app.websocket.manager import SessionManager
from app.websocket.protocol import PROTOCOL_VERSION, MessageType
from app.websocket.schemas import (
    Envelope,
    HelloPayload,
    TerminalClosePayload,
    TerminalErrorPayload,
    TerminalInputPayload,
    TerminalOpenedPayload,
    TerminalOpenPayload,
    TerminalOutputPayload,
    TerminalResizePayload,
    WelcomePayload,
)
from app.websocket.serializer import deserialize

logger: Any = structlog.get_logger("terminal.router")

#: Only a user already trusted to actuate this device may open its shell —
#: the same permission REST's own command-creation endpoints require, not a
#: new, terminal-specific permission (see docs/architecture/SECURITY.md).
_REQUIRED_PERMISSION = "commands.execute"


class TerminalGateway:
    """Coordinate one browser's terminal WebSocket connection end to end."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        event_bus: EventBus,
        session_manager: SessionManager,
        terminal_session_manager: TerminalSessionManager,
    ) -> None:
        self._settings = settings
        self._database = database
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._terminal_session_manager = terminal_session_manager

    async def handle_connection(self, websocket: WebSocket, device_id: UUID) -> None:
        """Run one browser connection end to end, always leaving state consistent on exit."""
        await websocket.accept()
        log = logger.bind(device_id=str(device_id))
        connection: BrowserConnection | None = None
        session_id: UUID | None = None
        tasks: list[asyncio.Task[None]] = []
        try:
            await self._handshake(websocket, device_id, log=log)
            connection = BrowserConnection(
                websocket, queue_size=self._settings.ws_outgoing_queue_size
            )
            open_payload = await self._await_open_request(websocket, log=log)
            session_id, is_new = await self._terminal_session_manager.attach(device_id, connection)
            if is_new:
                self._session_manager.send(
                    device_id,
                    Envelope(
                        protocol_version=PROTOCOL_VERSION,
                        message_type=MessageType.TERMINAL_OPEN,
                        payload=TerminalOpenPayload(
                            session_id=session_id, cols=open_payload.cols, rows=open_payload.rows
                        ).model_dump(mode="json"),
                    ),
                )
            else:
                shell = self._terminal_session_manager.shell_for(device_id)
                if shell is not None:
                    # Attached after the session was already confirmed open —
                    # the real TERMINAL_OPENED broadcast already happened
                    # before this browser existed, so synthesize an
                    # equivalent confirmation for this connection alone.
                    connection.enqueue(
                        Envelope(
                            protocol_version=PROTOCOL_VERSION,
                            message_type=MessageType.TERMINAL_OPENED,
                            payload=TerminalOpenedPayload(
                                session_id=session_id, shell=shell
                            ).model_dump(mode="json"),
                        )
                    )
                    # The shell already printed its prompt once, long before
                    # this browser existed, and won't reprint it just because
                    # someone new is watching — without this, a reattach
                    # shows a blank screen indistinguishable from "hung" even
                    # though the session is alive (see docs/agent/TERMINAL.md
                    # "Output replay on reattach"). Sent to this connection
                    # only, never broadcast — an already-attached browser has
                    # already seen this output and would see it duplicated.
                    buffered = self._terminal_session_manager.output_buffer_for(device_id)
                    if buffered:
                        connection.enqueue(
                            Envelope(
                                protocol_version=PROTOCOL_VERSION,
                                message_type=MessageType.TERMINAL_OUTPUT,
                                payload=TerminalOutputPayload(
                                    session_id=session_id, data=buffered
                                ).model_dump(mode="json"),
                            )
                        )
                # else: open is still in flight; the broadcast in
                # app/terminal/relay.py will reach this browser once the
                # agent confirms, same as every other attached browser.
            log = log.bind(session_id=str(session_id))
            log.info("terminal_browser_connected")
            tasks = [asyncio.create_task(connection.writer_loop())]
            await self._receive_loop(websocket, device_id, connection, log=log)
        except HandshakeTimeoutError:
            log.warning("terminal_handshake_timeout")
            await self._safe_close(websocket, CloseCode.HANDSHAKE_TIMEOUT, "handshake_timeout")
        except AuthenticationFailedError as error:
            log.warning("terminal_authentication_failed", reason=str(error))
            await self._safe_close(
                websocket, CloseCode.AUTHENTICATION_FAILED, "authentication_failed"
            )
        except DeviceUnavailableError as error:
            log.warning("terminal_device_unavailable", reason=str(error))
            await self._safe_close(websocket, CloseCode.DEVICE_UNAVAILABLE, "device_unavailable")
        except (ProtocolViolationError, WireProtocolViolationError) as error:
            log.warning("terminal_protocol_violation", reason=str(error))
            await self._safe_close(websocket, CloseCode.PROTOCOL_VIOLATION, "protocol_violation")
        except WebSocketDisconnect:
            log.info("terminal_browser_disconnected")
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if connection is not None:
                await self._terminal_session_manager.detach(device_id, connection)
            log.info("terminal_browser_connection_closed")

    async def _handshake(self, websocket: WebSocket, device_id: UUID, *, log: Any) -> Principal:
        """Authenticate the browser (HELLO, reusing the same user JWT REST accepts)."""
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=self._settings.ws_hello_timeout_seconds
            )
        except TimeoutError as error:
            raise HandshakeTimeoutError("No HELLO received within the handshake window") from error
        envelope = deserialize(raw)
        if envelope.message_type is not MessageType.HELLO:
            raise ProtocolViolationError("The first message on a connection must be HELLO")
        try:
            hello = HelloPayload.model_validate(envelope.payload)
        except ValidationError as error:
            raise ProtocolViolationError(f"Invalid HELLO payload: {error}") from error
        jwt_codec = self._build_jwt_codec()
        try:
            principal = decode_principal(jwt_codec, hello.token)
        except AuthDomainError as error:
            raise AuthenticationFailedError(str(error)) from error
        if principal.principal_type is not PrincipalType.USER:
            raise AuthenticationFailedError("Only a user credential may open a terminal session")
        if _REQUIRED_PERMISSION not in principal.permissions:
            raise AuthenticationFailedError(f"Permission '{_REQUIRED_PERMISSION}' is required")
        await self._require_connected_device(device_id)
        await websocket.send_text(
            Envelope(
                protocol_version=envelope.protocol_version,
                message_type=MessageType.WELCOME,
                payload=WelcomePayload(
                    session_id=uuid4(),
                    server_time=datetime.now(UTC),
                    protocol_version=envelope.protocol_version,
                    heartbeat_interval_seconds=self._settings.ws_heartbeat_interval_seconds,
                    heartbeat_timeout_seconds=self._settings.ws_heartbeat_timeout_seconds,
                ).model_dump(mode="json"),
            ).model_dump_json()
        )
        return principal

    def _build_jwt_codec(self) -> JWTCodec:
        if self._settings.jwt_secret is None:
            raise AuthenticationFailedError("JWT is not configured")
        return JWTCodec(
            secret=self._settings.jwt_secret.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            clock_skew_seconds=self._settings.jwt_clock_skew_seconds,
        )

    async def _require_connected_device(self, device_id: UUID) -> None:
        """Confirm the device exists, is enabled, and currently has an open agent session."""
        async with self._database.session_factory() as db_session:
            service = DeviceApplicationService(
                DeviceService(DeviceRepository(db_session)), self._event_bus
            )
            try:
                device = await service.get_device(device_id)
            except ApplicationError as error:
                raise DeviceUnavailableError(f"Device is not registered: {error}") from error
        if not device.enabled or device.status is DeviceStatus.DISABLED:
            raise DeviceUnavailableError("Device is disabled")
        if self._session_manager.get(device_id) is None:
            raise DeviceUnavailableError("Device is not currently connected")

    async def _await_open_request(self, websocket: WebSocket, *, log: Any) -> TerminalOpenPayload:
        """Wait for the browser's own ``TERMINAL_OPEN`` (cols/rows), right after WELCOME."""
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=self._settings.ws_hello_timeout_seconds
            )
        except TimeoutError as error:
            raise HandshakeTimeoutError("No TERMINAL_OPEN received after WELCOME") from error
        envelope = deserialize(raw)
        if envelope.message_type is not MessageType.TERMINAL_OPEN:
            raise ProtocolViolationError("Expected TERMINAL_OPEN immediately after WELCOME")
        try:
            return TerminalOpenPayload.model_validate(envelope.payload)
        except ValidationError as error:
            raise ProtocolViolationError(f"Invalid TERMINAL_OPEN payload: {error}") from error

    async def _receive_loop(
        self,
        websocket: WebSocket,
        device_id: UUID,
        connection: BrowserConnection,
        *,
        log: Any,
    ) -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = deserialize(raw)
            except WireProtocolViolationError:
                log.warning("terminal_invalid_message", raw_length=len(raw))
                continue
            session_id = self._terminal_session_manager.session_id_for(device_id)
            if session_id is None:
                # The session already ended (idle timeout, shell exit, or an
                # explicit close from another attached tab) — nothing left
                # to relay input/resize to; a stale client will get a fresh
                # TERMINAL_OPEN on its next reconnect.
                continue
            try:
                if envelope.message_type is MessageType.TERMINAL_INPUT:
                    self._relay_to_agent(
                        device_id,
                        MessageType.TERMINAL_INPUT,
                        TerminalInputPayload.model_validate(
                            {**envelope.payload, "session_id": str(session_id)}
                        ),
                    )
                elif envelope.message_type is MessageType.TERMINAL_RESIZE:
                    self._relay_to_agent(
                        device_id,
                        MessageType.TERMINAL_RESIZE,
                        TerminalResizePayload.model_validate(
                            {**envelope.payload, "session_id": str(session_id)}
                        ),
                    )
                elif envelope.message_type is MessageType.TERMINAL_CLOSE:
                    self._relay_to_agent(
                        device_id,
                        MessageType.TERMINAL_CLOSE,
                        TerminalClosePayload.model_validate(
                            {**envelope.payload, "session_id": str(session_id)}
                        ),
                    )
                    return
                elif envelope.message_type is MessageType.TERMINAL_OPEN:
                    continue  # already attached; nothing further to do
                else:
                    log.warning(
                        "terminal_unexpected_message_type", message_type=envelope.message_type
                    )
            except ValidationError:
                log.warning("terminal_invalid_payload", message_type=envelope.message_type)
                continue

    def _relay_to_agent(
        self,
        device_id: UUID,
        message_type: MessageType,
        payload: TerminalInputPayload | TerminalResizePayload | TerminalClosePayload,
    ) -> None:
        envelope = Envelope(
            protocol_version=PROTOCOL_VERSION,
            message_type=message_type,
            payload=payload.model_dump(mode="json"),
        )
        if self._session_manager.send(device_id, envelope):
            return
        # The agent dropped its connection to the server between this
        # session opening and now — every browser attached to this device
        # needs to know, not just the one whose message triggered this.
        error = Envelope(
            protocol_version=PROTOCOL_VERSION,
            message_type=MessageType.TERMINAL_ERROR,
            payload=TerminalErrorPayload(
                session_id=None,
                code="agent_disconnected",
                message="The device is no longer connected",
            ).model_dump(mode="json"),
        )
        for browser in self._terminal_session_manager.browsers_for(device_id):
            with contextlib.suppress(BackpressureExceededError):
                browser.enqueue(error)

    async def _safe_close(self, websocket: WebSocket, code: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            await websocket.close(code=code, reason=reason)


def build_terminal_router(settings: Settings) -> APIRouter:
    """Build the browser-facing terminal WebSocket route.

    A factory rather than a module-level ``router``, exactly like
    ``app/websocket/router.py``'s ``build_websocket_router`` — so the path
    stays configurable via ``Settings.terminal_websocket_path``.
    """
    router = APIRouter(tags=["Terminal"])

    @router.websocket(f"{settings.terminal_websocket_path}/{{device_id}}")
    async def terminal_endpoint(websocket: WebSocket, device_id: UUID) -> None:
        """Accept and run one browser's terminal connection for its entire lifetime."""
        container = websocket.app.state.container
        gateway = TerminalGateway(
            settings=container.settings(),
            database=container.database(),
            event_bus=container.event_bus(),
            session_manager=container.session_manager(),
            terminal_session_manager=container.terminal_session_manager(),
        )
        await gateway.handle_connection(websocket, device_id)

    return router
