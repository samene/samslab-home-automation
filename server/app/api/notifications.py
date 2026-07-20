"""FastAPI delivery adapter for the Notification Framework's Settings-page surface.

Contains no business logic: each route only resolves ``NotificationService``
and returns the schema it produces — same shape as ``app/api/camera.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_notification_service
from app.notifications.schemas import NotificationStatusResponse, TestNotificationResult
from app.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get(
    "/status",
    response_model=NotificationStatusResponse,
    summary="Report every provider's current status",
)
async def get_status(
    service: NotificationService = Depends(get_notification_service),
) -> NotificationStatusResponse:
    """Configuration + most recent delivery attempt for every registered provider."""
    return await service.get_status()


@router.post(
    "/test",
    response_model=list[TestNotificationResult],
    summary="Send a test notification to every registered provider",
)
async def send_test_notification(
    service: NotificationService = Depends(get_notification_service),
) -> list[TestNotificationResult]:
    """Send a test message; requires no workflow to run. Always 200 — a failed send is a result, not an error."""
    return await service.send_test_notification()
