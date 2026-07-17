"""FastAPI delivery adapter for live camera streaming.

Contains no business logic: each route only resolves the Camera application
service and returns the DTO it produces. The browser only ever receives a
``playback_url`` this layer builds from server-side MediaMTX configuration —
it never talks to the Raspberry Pi directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.application.dto.camera_dto import CameraStatusDTO, CameraStopDTO
from app.application.events.bus import EventBus
from app.application.services.camera_service import CameraApplicationService
from app.core.database import Database
from app.dependencies import get_database, get_event_bus

router = APIRouter(prefix="/camera", tags=["Camera"])


def get_camera_application_service(
    request: Request,
    database: Database = Depends(get_database),
    event_bus: EventBus = Depends(get_event_bus),
) -> CameraApplicationService:
    """Build the Camera application service; it manages its own sessions per operation.

    Unlike other application services, this one is not bound to one
    request-scoped transaction (see ``CameraApplicationService``'s docstring
    for why) — it opens and commits its own short-lived session per step.
    """
    settings = request.app.state.container.settings()
    return CameraApplicationService(
        database=database,
        event_bus=event_bus,
        mediamtx_host=settings.mediamtx_host,
        mediamtx_playback_port=settings.mediamtx_playback_port,
        mediamtx_playback_scheme=settings.mediamtx_playback_scheme,
        mediamtx_jwt_signer=request.app.state.container.mediamtx_jwt_signer(),
        mediamtx_jwt_ttl_seconds=settings.mediamtx_jwt_ttl_seconds,
        mediamtx_jwt_publish_ttl_seconds=settings.mediamtx_jwt_publish_ttl_seconds,
        stream_name=settings.camera_stream_name,
        command_timeout_seconds=settings.camera_command_timeout_seconds,
        command_poll_interval_seconds=settings.camera_command_poll_interval_seconds,
    )


@router.post("/start", response_model=CameraStatusDTO, summary="Start the live camera stream")
async def start_stream(
    service: CameraApplicationService = Depends(get_camera_application_service),
) -> CameraStatusDTO:
    """Dispatch ``camera.stream.start`` and wait for the device to confirm it's live."""
    return await service.start_stream()


@router.post("/stop", response_model=CameraStopDTO, summary="Stop the live camera stream")
async def stop_stream(
    service: CameraApplicationService = Depends(get_camera_application_service),
) -> CameraStopDTO:
    """Dispatch ``camera.stream.stop`` and wait for the device to confirm it's stopped."""
    return await service.stop_stream()


@router.get("/status", response_model=CameraStatusDTO, summary="Report the live stream's state")
async def get_status(
    service: CameraApplicationService = Depends(get_camera_application_service),
) -> CameraStatusDTO:
    """Derive current stream state from the most recent start/stop commands."""
    return await service.get_status()
