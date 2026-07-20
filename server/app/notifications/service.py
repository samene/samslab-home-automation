"""Formats notification events into messages and dispatches them to every registered provider.

This is the "Notification Service" in the architecture the Workflow Engine
never sees past ``app.notifications.events``: ``app.notifications.dispatcher``
subscribes ``notify_workflow_completed``/``notify_workflow_failed`` to the
shared event bus, and ``app/api/notifications.py`` calls
``send_test_notification``/``get_status`` directly for the Settings page.
Nothing here is Telegram-specific — providers are injected, generic
``NotificationProvider``s (see ``providers/base.py``); adding Slack/Discord/
Push/Email later is only ever a new provider appended where this service is
built (``app.core.container``), never a change to this file.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.database import Database
from app.core.s3_client import S3Client
from app.notifications.events import WorkflowCompleted, WorkflowFailed
from app.notifications.metrics import NOTIFICATIONS_FAILED_TOTAL, NOTIFICATIONS_SENT_TOTAL
from app.notifications.models import NotificationLog
from app.notifications.providers.base import (
    NotificationMessage,
    NotificationProvider,
    NotificationResult,
)
from app.notifications.schemas import (
    NotificationProviderStatus,
    NotificationStatusResponse,
    TestNotificationResult,
)

logger = structlog.get_logger(__name__)

# Purely cosmetic: a handful of built-in command types get a friendlier label
# in a Telegram message than their raw dot-namespaced form. The underlying
# WorkflowFailed event always carries the real command_type regardless.
_FRIENDLY_STEP_LABELS = {
    "camera.snapshot": "Take Snapshot",
    "camera.stream.start": "Start Camera Stream",
    "camera.stream.stop": "Stop Camera Stream",
    "camera.record.start": "Start Recording",
    "camera.record.stop": "Stop Recording",
    "pump.trigger": "Trigger Pump",
}


def _friendly_step_label(command_type: str | None) -> str:
    if command_type is None:
        return "Unknown"
    return _FRIENDLY_STEP_LABELS.get(command_type, command_type)


def _format_workflow_completed(event: WorkflowCompleted) -> str:
    return (
        "✅ Workflow Completed\n\n"
        f"Workflow: {event.workflow_name}\n\n"
        "Started:\n"
        f"{event.started_at.strftime('%H:%M:%S')}\n\n"
        "Completed:\n"
        f"{event.completed_at.strftime('%H:%M:%S')}\n\n"
        "Duration:\n"
        f"{round(event.duration_seconds)} seconds\n\n"
        "Triggered by:\n"
        f"{event.trigger_source}"
    )


def _format_workflow_failed(event: WorkflowFailed) -> str:
    return (
        "❌ Workflow Failed\n\n"
        "Workflow:\n"
        f"{event.workflow_name}\n\n"
        "Failed Step:\n"
        f"{_friendly_step_label(event.failed_step)}\n\n"
        "Duration:\n"
        f"{round(event.duration_seconds)} seconds\n\n"
        "Error:\n"
        f"{event.error_message}"
    )


class NotificationService:
    """Formats events, dispatches to every registered provider, records the outcome."""

    def __init__(
        self,
        *,
        database: Database | None,
        providers: Sequence[NotificationProvider],
        s3_client: S3Client | None = None,
    ) -> None:
        """``database``/``s3_client`` are optional: delivery works without either.

        With no database, only the delivery-history log becomes a no-op;
        with no S3 client, a thumbnail is simply never attached (the
        workflow name/times/etc. still send as plain text) — see
        ``_resolve_photo_bytes``.
        """
        self._database = database
        self._providers = list(providers)
        self._s3_client = s3_client

    async def notify_workflow_completed(self, event: WorkflowCompleted) -> None:
        """The ``WorkflowCompleted`` event-bus subscriber — never raises, see ``_dispatch``."""
        await self._dispatch(
            _format_workflow_completed(event),
            event_type="WORKFLOW_COMPLETED",
            workflow_id=event.workflow_id,
            workflow_name=event.workflow_name,
            thumbnail_object_key=event.thumbnail_object_key,
        )

    async def notify_workflow_failed(self, event: WorkflowFailed) -> None:
        """The ``WorkflowFailed`` event-bus subscriber — never raises, see ``_dispatch``."""
        await self._dispatch(
            _format_workflow_failed(event),
            event_type="WORKFLOW_FAILED",
            workflow_id=event.workflow_id,
            workflow_name=event.workflow_name,
            thumbnail_object_key=event.thumbnail_object_key,
        )

    async def send_test_notification(self) -> list[TestNotificationResult]:
        """Send a test message to every registered provider; requires no workflow to run."""
        text = "🔔 Test Notification\n\nThis is a test notification from Sam's Lab."
        outcomes = await self._dispatch(
            text, event_type="TEST", workflow_id=None, workflow_name=None, thumbnail_object_key=None
        )
        return [
            TestNotificationResult(
                provider=provider_name,
                success=result.success,
                duration_ms=round(result.duration_seconds * 1000),
                error_message=result.error_message,
            )
            for provider_name, result in outcomes
        ]

    async def get_status(self) -> NotificationStatusResponse:
        """Every registered provider's current configuration plus its most recent delivery attempt."""
        providers = []
        for provider in self._providers:
            last_attempt_at, last_success, last_error = await self._last_attempt(provider.name)
            providers.append(
                NotificationProviderStatus(
                    provider=provider.name,
                    enabled=provider.enabled,
                    configured=provider.is_configured,
                    last_attempt_at=last_attempt_at,
                    last_success=last_success,
                    last_error=last_error,
                )
            )
        return NotificationStatusResponse(providers=providers)

    async def _dispatch(
        self,
        text: str,
        *,
        event_type: str,
        workflow_id: UUID | None,
        workflow_name: str | None,
        thumbnail_object_key: str | None,
    ) -> list[tuple[str, NotificationResult]]:
        """Send ``text`` to every registered provider; a provider failure is recorded, never raised.

        This is the one choke point every caller (the two event subscribers
        above, and ``send_test_notification``) goes through — the guarantee
        that a notification failure can never propagate to whatever
        triggered it is enforced here, once, rather than by every caller
        remembering to catch its own exceptions. The thumbnail (if any) is
        fetched once here and shared across every provider, rather than each
        provider re-fetching the same object.
        """
        photo_bytes = await self._resolve_photo_bytes(thumbnail_object_key)
        message = NotificationMessage(
            text=text,
            event_type=event_type,
            photo_bytes=photo_bytes,
            photo_filename=f"{workflow_name or 'notification'}.jpg" if photo_bytes else None,
        )
        outcomes: list[tuple[str, NotificationResult]] = []
        for provider in self._providers:
            try:
                result = await provider.send(message)
            except Exception as error:  # pragma: no cover - defensive; providers must not raise
                result = NotificationResult(
                    success=False, duration_seconds=0.0, error_message=str(error)
                )
                logger.warning(
                    "notification_provider_raised",
                    provider=provider.name,
                    event_type=event_type,
                    error=str(error),
                )

            if result.success:
                NOTIFICATIONS_SENT_TOTAL.labels(provider=provider.name).inc()
            else:
                NOTIFICATIONS_FAILED_TOTAL.labels(provider=provider.name).inc()
                logger.warning(
                    "notification_failed",
                    provider=provider.name,
                    event_type=event_type,
                    workflow=workflow_name,
                    delivery_duration_seconds=round(result.duration_seconds, 3),
                    error=result.error_message,
                )
            if result.success:
                logger.info(
                    "notification_sent",
                    provider=provider.name,
                    event_type=event_type,
                    workflow=workflow_name,
                    delivery_duration_seconds=round(result.duration_seconds, 3),
                )

            await self._record(
                provider=provider.name,
                event_type=event_type,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                result=result,
            )
            outcomes.append((provider.name, result))
        return outcomes

    async def _resolve_photo_bytes(self, thumbnail_object_key: str | None) -> bytes | None:
        """Fetch a thumbnail's raw bytes directly from S3 — never a presigned URL.

        Best-effort: no S3 client configured, no thumbnail on the event, or
        the fetch itself failing all fall back to the same thing — a
        text-only message — rather than losing the notification entirely.
        ``get_object_bytes`` is a real network call (via boto3, which is
        synchronous), so it runs in the default executor rather than
        blocking the event loop.
        """
        if thumbnail_object_key is None or self._s3_client is None:
            return None
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._s3_client.get_object_bytes, thumbnail_object_key
            )
        except Exception as error:  # pragma: no cover - defensive
            logger.warning(
                "notification_thumbnail_fetch_failed",
                object_key=thumbnail_object_key,
                error=str(error),
            )
            return None

    async def _record(
        self,
        *,
        provider: str,
        event_type: str,
        workflow_id: UUID | None,
        workflow_name: str | None,
        result: NotificationResult,
    ) -> None:
        """Best-effort audit write — a logging failure must never affect delivery's own success/failure."""
        if self._database is None:
            return
        try:
            async with self._database.session_factory() as session:
                session.add(
                    NotificationLog(
                        provider=provider,
                        event_type=event_type,
                        workflow_id=workflow_id,
                        workflow_name=workflow_name,
                        success=result.success,
                        error_message=result.error_message,
                        duration_ms=round(result.duration_seconds * 1000),
                    )
                )
                await session.commit()
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("notification_log_write_failed", provider=provider, error=str(error))

    async def _last_attempt(self, provider: str) -> tuple[datetime | None, bool | None, str | None]:
        if self._database is None:
            return None, None, None
        try:
            async with self._database.session_factory() as session:
                statement = (
                    select(NotificationLog)
                    .where(NotificationLog.provider == provider)
                    .order_by(NotificationLog.created_at.desc())
                    .limit(1)
                )
                row = (await session.execute(statement)).scalar_one_or_none()
                await session.commit()
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("notification_log_read_failed", provider=provider, error=str(error))
            return None, None, None
        if row is None:
            return None, None, None
        return row.created_at, row.success, row.error_message
