"""Notification events — what the Workflow Engine emits, and nothing else.

These are the one seam between the Workflow Engine and the Notification
Framework: ``WorkflowApplicationService`` constructs and publishes these (via
the shared ``EventBus``, see ``app.application.events.bus``) when a run
reaches a terminal state, and never imports anything else from
``app.notifications`` — no provider, no ``NotificationService``, nothing. The
engine has no idea Telegram (or anything else) is listening; it only knows
these two event shapes exist. See ``app.notifications.dispatcher`` for the
other end of that seam.

Distinct from ``app.application.events.domain_events`` on purpose: those are
generic, already-established cross-cutting domain events (``CommandCompleted``,
``DeviceRegistered``, ...); these two are specific to notification delivery
and live in this package so the Notification Framework's own shape (events,
providers, service, dispatcher) is self-contained in one place, exactly as
laid out for this feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkflowCompleted:
    """Published once a workflow run finishes in a COMPLETED state.

    ``thumbnail_object_key``/``video_object_key`` are plain S3 key
    references, not URLs — the Workflow Engine only identifies *which*
    saved-media object (if any) this run produced; resolving one into
    actual bytes is ``NotificationService``'s job (see its module
    docstring), so this event stays a pure data reference with no S3 client
    dependency of its own. Mutually exclusive: a run that produced a video
    recording never also sets ``thumbnail_object_key`` — see
    ``WorkflowApplicationService._resolve_notification_media``, since a
    provider should attach the actual recording instead of a still preview
    when one exists, not both. All four are ``None`` when the run generated
    no media at all.
    """

    workflow_id: UUID
    workflow_name: str
    execution_id: UUID
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    status: str
    trigger_source: str
    thumbnail_object_key: str | None = None
    video_object_key: str | None = None
    video_filename: str | None = None
    video_size_bytes: int | None = None
    # Passed through to Telegram's sendVideo as explicit width/height/
    # duration hints (see TelegramProvider._build_request) — without them, a
    # client can render the video at the wrong aspect ratio (e.g. stretched)
    # before/instead of introspecting the file's own container metadata.
    video_width: int | None = None
    video_height: int | None = None
    video_duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowFailed:
    """Published once a workflow run finishes in a FAILED state.

    ``failed_step`` is the failed step's ``command_type`` (e.g.
    ``"camera.snapshot"``) when it could be resolved from the run's step-run
    history, or ``None`` if the run failed before any step recorded one
    (e.g. no device registered) — best-effort, never worth failing the whole
    notification over.
    """

    workflow_id: UUID
    workflow_name: str
    execution_id: UUID
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    status: str
    trigger_source: str
    error_message: str
    failed_step: str | None
    thumbnail_object_key: str | None = None
    video_object_key: str | None = None
    video_filename: str | None = None
    video_size_bytes: int | None = None
    # Passed through to Telegram's sendVideo as explicit width/height/
    # duration hints (see TelegramProvider._build_request) — without them, a
    # client can render the video at the wrong aspect ratio (e.g. stretched)
    # before/instead of introspecting the file's own container metadata.
    video_width: int | None = None
    video_height: int | None = None
    video_duration_seconds: int | None = None
