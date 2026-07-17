"""FastAPI delivery adapter for the WebSocket gateway: the WS route and admin REST endpoints."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.application.exceptions import NotFoundError
from app.config.settings import Settings
from app.domains.auth.dependencies import RequirePermission
from app.websocket.gateway import WebSocketGateway
from app.websocket.manager import SessionManager
from app.websocket.schemas import SessionSummaryDTO


def _get_session_manager(request: Request) -> SessionManager:
    """Resolve the shared, per-application session registry from the DI container."""
    session_manager: SessionManager = request.app.state.container.session_manager()
    return session_manager


def build_websocket_router(settings: Settings) -> APIRouter:
    """Build the WebSocket route and its read-only admin REST endpoints.

    A factory rather than a module-level ``router`` so the WS path stays
    configurable via ``Settings.websocket_path`` without a hardcoded decorator path.
    """
    router = APIRouter(tags=["WebSocket"])

    @router.websocket(settings.websocket_path)
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Accept and run one agent connection for its entire lifetime."""
        container = websocket.app.state.container
        session_manager: SessionManager = container.session_manager()
        current_task = asyncio.current_task()
        if current_task is not None:
            session_manager.track(current_task)
        gateway = WebSocketGateway(
            settings=container.settings(),
            database=container.database(),
            event_bus=container.event_bus(),
            session_manager=session_manager,
        )
        await gateway.handle_connection(websocket)

    @router.get(
        f"{settings.websocket_path}/sessions",
        response_model=list[SessionSummaryDTO],
        summary="List every currently connected device session.",
    )
    async def list_sessions(
        session_manager: SessionManager = Depends(_get_session_manager),
        _principal: object = Depends(RequirePermission("system.admin")),
    ) -> list[SessionSummaryDTO]:
        """Read-only snapshot of every in-memory session; never persisted."""
        return session_manager.list_sessions()

    @router.get(
        f"{settings.websocket_path}/sessions/{{device_id}}",
        response_model=SessionSummaryDTO,
        summary="Look up one device's current session.",
    )
    async def get_session(
        device_id: UUID,
        session_manager: SessionManager = Depends(_get_session_manager),
        _principal: object = Depends(RequirePermission("system.admin")),
    ) -> SessionSummaryDTO:
        """Return one device's session, or a 404 if it is not currently connected."""
        summary = session_manager.get_summary(device_id)
        if summary is None:
            raise NotFoundError(f"No active session for device '{device_id}'")
        return summary

    @router.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Expose Prometheus-format metrics for the WebSocket gateway."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
