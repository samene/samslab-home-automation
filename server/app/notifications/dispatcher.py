"""Wires the Notification Service to the two events the Workflow Engine emits.

Mirrors ``app.application.events.logging_subscriber.register_logging_subscriber``
in spirit — called once, from ``app.core.container.build_container``, alongside
it. This is the other end of the seam ``app.notifications.events`` describes:
the Workflow Engine only ever publishes ``WorkflowCompleted``/``WorkflowFailed``
on the shared event bus; it never imports this module or knows it exists.
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.events.bus import EventBus
from app.notifications.events import WorkflowCompleted, WorkflowFailed
from app.notifications.service import NotificationService


def register_notification_subscribers(
    event_bus: EventBus, notification_service_factory: Callable[[], NotificationService]
) -> None:
    """Subscribe to every notification-triggering event, resolving the service lazily.

    ``notification_service_factory`` — a dependency-injector ``Singleton``
    provider is itself exactly this: a zero-arg callable — is called at
    *publish* time, not here. Resolving (and thereby constructing/caching)
    ``NotificationService`` eagerly at wiring time would freeze its
    ``database`` dependency to whatever it was when ``build_container()``
    ran, silently ignoring a test's later
    ``container.database.override(...)`` (the same pattern
    ``app/main.py``'s ``_build_schedule_on_fire`` already defers for exactly
    this reason) — this bug was caught by ``test_notifications_api.py``
    writing to the wrong (schema-less) in-memory database.
    """

    async def on_workflow_completed(event: WorkflowCompleted) -> None:
        await notification_service_factory().notify_workflow_completed(event)

    async def on_workflow_failed(event: WorkflowFailed) -> None:
        await notification_service_factory().notify_workflow_failed(event)

    event_bus.subscribe(WorkflowCompleted, on_workflow_completed)
    event_bus.subscribe(WorkflowFailed, on_workflow_failed)
