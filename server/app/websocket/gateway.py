"""Full WebSocket connection lifecycle: accept, authenticate, and orchestrate one device.

Transport only. Nothing here executes a command, touches GPIO, or accesses a
repository directly — the one cross-domain call this module makes
(``DeviceApplicationService``) is the same Application Layer seam REST uses,
so a future MQTT or gRPC transport could reuse it identically.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.application.dto.device_dto import DeviceDTO
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
from app.domains.devices.schemas import HeartbeatInput
from app.domains.devices.service import DeviceService
from app.websocket.connection import Connection
from app.websocket.constants import CloseCode
from app.websocket.exceptions import (
    AuthenticationFailedError,
    BackpressureExceededError,
    DuplicateSessionError,
    GoodbyeReceived,
    HandshakeTimeoutError,
    ProtocolVersionUnsupportedError,
    ProtocolViolationError,
)
from app.websocket.handlers import dispatch_message
from app.websocket.heartbeat import HeartbeatMonitor
from app.websocket.manager import SessionManager
from app.websocket.metrics import AUTHENTICATION_FAILURES_TOTAL, CONNECTION_DURATION
from app.websocket.protocol import PROTOCOL_VERSION, MessageType, negotiate_protocol_version
from app.websocket.schemas import Envelope, GoodbyePayload, HelloPayload, WelcomePayload
from app.websocket.serializer import deserialize
from app.websocket.session import ConnectionState, Session

logger: Any = structlog.get_logger("websocket.gateway")


class WebSocketGateway:
    """Coordinate one WebSocket connection from accept through cleanup."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        event_bus: EventBus,
        session_manager: SessionManager,
    ) -> None:
        """Bind to the shared, per-application infrastructure this connection will use."""
        self._settings = settings
        self._database = database
        self._event_bus = event_bus
        self._session_manager = session_manager

    async def handle_connection(self, websocket: WebSocket) -> None:
        """Run one connection end to end, always leaving state consistent on exit."""
        await websocket.accept()
        connection_id = uuid4()
        remote_ip = websocket.client.host if websocket.client else None
        log = logger.bind(connection_id=str(connection_id), remote_ip=remote_ip)
        started_at = monotonic()
        session: Session | None = None
        tasks: list[asyncio.Task[None]] = []
        registered = False
        try:
            principal, hello, requested_version, device_id = await self._handshake(
                websocket, log=log
            )
            protocol_version = negotiate_protocol_version(requested_version)
            device = await self._get_enabled_device(device_id)
            connection = Connection(
                websocket,
                queue_size=self._settings.ws_outgoing_queue_size,
                ack_timeout_seconds=self._settings.ws_message_ack_timeout_seconds,
                ack_max_retries=self._settings.ws_message_ack_max_retries,
            )
            now = datetime.now(UTC)
            session = Session(
                device_id=device.id,
                connection_id=connection_id,
                connected_at=now,
                last_seen=now,
                protocol_version=protocol_version,
                authenticated_principal=principal,
                connection=connection,
                agent_version=hello.agent_version,
                remote_ip=remote_ip,
                connection_state=ConnectionState.AUTHENTICATING,
            )
            await self._session_manager.register(session)
            registered = True
            session.connection_state = ConnectionState.OPEN
            # Enqueued immediately, with no `await` in between: once registered,
            # this session is visible to the Command Dispatcher's own poll loop,
            # which could otherwise enqueue a COMMAND for an already-pending
            # command onto this same connection before WELCOME — an agent must
            # always be able to assume WELCOME is the first message it receives.
            connection.enqueue(
                Envelope(
                    protocol_version=protocol_version,
                    message_type=MessageType.WELCOME,
                    payload=WelcomePayload(
                        session_id=connection_id,
                        server_time=now,
                        protocol_version=protocol_version,
                        heartbeat_interval_seconds=self._settings.ws_heartbeat_interval_seconds,
                        heartbeat_timeout_seconds=self._settings.ws_heartbeat_timeout_seconds,
                    ).model_dump(mode="json"),
                )
            )
            log = log.bind(device_id=str(device.id))
            log.info("websocket_connected", agent_version=hello.agent_version)
            await self._mark_device(
                device.id, hello, protocol_version, DeviceStatus.ONLINE, log=log
            )
            tasks = [
                asyncio.create_task(connection.writer_loop()),
                asyncio.create_task(connection.ack_watchdog_loop()),
                asyncio.create_task(
                    HeartbeatMonitor(
                        session,
                        connection,
                        interval_seconds=self._settings.ws_heartbeat_interval_seconds,
                        heartbeat_timeout_seconds=self._settings.ws_heartbeat_timeout_seconds,
                        idle_timeout_seconds=self._settings.ws_idle_timeout_seconds,
                        on_timeout=self._make_timeout_handler(connection),
                    ).run()
                ),
            ]
            await self._receive_loop(websocket, session, connection, log=log)
        except HandshakeTimeoutError:
            log.warning("websocket_handshake_timeout")
            await self._safe_close(websocket, CloseCode.HANDSHAKE_TIMEOUT, "handshake_timeout")
        except AuthenticationFailedError as error:
            AUTHENTICATION_FAILURES_TOTAL.inc()
            log.warning("websocket_authentication_failed", reason=str(error))
            await self._safe_close(
                websocket, CloseCode.AUTHENTICATION_FAILED, "authentication_failed"
            )
        except ProtocolVersionUnsupportedError as error:
            log.warning("websocket_protocol_version_unsupported", reason=str(error))
            await self._safe_close(
                websocket, CloseCode.UNSUPPORTED_PROTOCOL_VERSION, "unsupported_protocol_version"
            )
        except DuplicateSessionError as error:
            log.warning("websocket_duplicate_session", reason=str(error))
            await self._safe_close(websocket, CloseCode.DUPLICATE_SESSION, "duplicate_session")
        except ProtocolViolationError as error:
            log.warning("websocket_protocol_violation", reason=str(error))
            await self._safe_close(websocket, CloseCode.PROTOCOL_VIOLATION, "protocol_violation")
        except BackpressureExceededError:
            log.warning("websocket_backpressure_exceeded")
            await self._safe_close(websocket, CloseCode.BACKPRESSURE, "backpressure_exceeded")
        except GoodbyeReceived:
            log.info("websocket_goodbye_received")
        except WebSocketDisconnect:
            log.info("websocket_disconnected")
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if registered and session is not None:
                session.connection_state = ConnectionState.CLOSED
                await self._session_manager.unregister(session.device_id)
                await self._mark_offline_best_effort(session.device_id, log=log)
                CONNECTION_DURATION.observe(monotonic() - started_at)
                log.info("websocket_connection_closed")

    async def _handshake(
        self, websocket: WebSocket, *, log: Any
    ) -> tuple[Principal, HelloPayload, int, UUID]:
        """Wait for and validate the mandatory first ``HELLO`` message."""
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
        if principal.principal_type is not PrincipalType.DEVICE or principal.device_id is None:
            raise AuthenticationFailedError("Only device credentials may connect to this gateway")
        return principal, hello, envelope.protocol_version, principal.device_id

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

    async def _get_enabled_device(self, device_id: UUID) -> DeviceDTO:
        """Confirm the device still exists and is enabled at connection time.

        A device token is a stateless JWT with no revocation list, so a
        device disabled after its token was issued must still be rejected —
        this live check is what catches that.
        """
        async with self._database.session_factory() as db_session:
            service = DeviceApplicationService(
                DeviceService(DeviceRepository(db_session)), self._event_bus
            )
            try:
                device = await service.get_device(device_id)
            except ApplicationError as error:
                raise AuthenticationFailedError(f"Device is not registered: {error}") from error
        if not device.enabled or device.status is DeviceStatus.DISABLED:
            raise AuthenticationFailedError("Device is disabled")
        return device

    async def _mark_device(
        self,
        device_id: UUID,
        hello: HelloPayload,
        protocol_version: int,
        status: DeviceStatus,
        *,
        log: Any,
    ) -> None:
        async with self._database.session_factory() as db_session:
            service = DeviceApplicationService(
                DeviceService(DeviceRepository(db_session)), self._event_bus
            )
            try:
                await service.heartbeat(
                    device_id,
                    HeartbeatInput(
                        status=status,
                        agent_version=hello.agent_version,
                        protocol_version=str(protocol_version),
                    ),
                )
                await db_session.commit()
            except ApplicationError as error:
                await db_session.rollback()
                log.warning("websocket_device_heartbeat_failed", reason=str(error))

    async def _mark_offline_best_effort(self, device_id: UUID, *, log: Any) -> None:
        async with self._database.session_factory() as db_session:
            service = DeviceApplicationService(
                DeviceService(DeviceRepository(db_session)), self._event_bus
            )
            try:
                await service.heartbeat(
                    device_id,
                    HeartbeatInput(
                        status=DeviceStatus.OFFLINE,
                        agent_version="unknown",
                        protocol_version=str(PROTOCOL_VERSION),
                    ),
                )
                await db_session.commit()
            except ApplicationError as error:
                await db_session.rollback()
                log.warning("websocket_offline_mark_failed", reason=str(error))

    def _make_timeout_handler(self, connection: Connection) -> Any:
        async def _on_timeout(session: Session, reason: str) -> None:
            await connection.close(code=CloseCode.HEARTBEAT_TIMEOUT, reason=reason)

        return _on_timeout

    async def _receive_loop(
        self, websocket: WebSocket, session: Session, connection: Connection, *, log: Any
    ) -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = deserialize(raw)
            except ProtocolViolationError:
                log.warning("websocket_invalid_message", raw_length=len(raw))
                raise
            if connection.is_duplicate(envelope.message_id):
                log.info("websocket_duplicate_message", message_id=str(envelope.message_id))
                continue
            connection.mark_seen(envelope.message_id)
            if envelope.message_type is MessageType.GOODBYE:
                with contextlib.suppress(ValidationError):
                    GoodbyePayload.model_validate(envelope.payload)
                raise GoodbyeReceived()
            await dispatch_message(
                session=session,
                connection=connection,
                envelope=envelope,
                log=log,
                event_bus=self._event_bus,
            )

    async def _safe_close(self, websocket: WebSocket, code: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            await websocket.close(code=code, reason=reason)
