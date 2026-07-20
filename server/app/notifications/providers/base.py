"""The one contract every notification provider implements.

``NotificationService`` only ever calls through this interface — it never
knows a provider's own implementation (Telegram Bot API, a future SMTP
client, a future Slack/Discord webhook, a future push-notification
service). Adding a provider is always: implement this ``Protocol``, register
an instance where ``NotificationService`` is built (see
``app.core.container``) — never a change to ``NotificationService`` itself,
and never anything the Workflow Engine needs to know about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """An already-formatted message, provider-agnostic.

    Formatting an event (``WorkflowCompleted``/``WorkflowFailed``) into
    human-readable text is ``NotificationService``'s job, not a provider's —
    every provider just sends the same plain text to its own destination.
    ``event_type`` is carried along only for logging/metrics labeling.

    ``photo_bytes``, when present, is already-fetched image bytes (a
    workflow's snapshot thumbnail — see ``NotificationService``, which
    resolves an event's ``thumbnail_object_key`` into these bytes via direct
    S3 ``GetObject``, never a presigned URL) for a provider that supports
    attaching one to send alongside ``text`` as a caption, instead of a
    plain text-only message. A provider without photo support is free to
    ignore it and always send ``text`` alone.
    """

    text: str
    event_type: str
    photo_bytes: bytes | None = None
    photo_filename: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """What a provider's ``send()`` produced — success or a description of why not.

    Never raises past ``send()``: a provider failure is data, not an
    exception, since a failed notification must never propagate into
    whatever triggered it (see ``NotificationService.dispatch``).
    """

    success: bool
    duration_seconds: float
    error_message: str | None = None


class NotificationProvider(Protocol):
    """Something that can deliver one already-formatted message somewhere."""

    @property
    def name(self) -> str:
        """This provider's stable identifier, used for logging/metrics labels (e.g. ``"telegram"``)."""

    @property
    def enabled(self) -> bool:
        """Whether an operator has switched this provider on (independent of whether it's configured)."""

    @property
    def is_configured(self) -> bool:
        """Whether this provider has the credentials it needs to actually send anything."""

    async def send(self, message: NotificationMessage) -> NotificationResult:
        """Deliver ``message``; must never raise — failures are reported via ``NotificationResult``."""
