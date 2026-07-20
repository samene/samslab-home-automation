"""SQLAlchemy persistence model owned exclusively by the Notification Framework.

One row per delivery attempt — durable history for the Settings page's
"current status" display, not a config store (Telegram credentials stay in
``Settings``/environment, matching every other third-party credential in this
codebase; see ``app.notifications.config``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationLog(Base):
    """One notification delivery attempt, successful or not.

    ``workflow_id``/``workflow_name`` are a plain, unconstrained columns —
    same convention as ``WorkflowStepRun.command_id``: a cross-cutting
    reference with no ``ForeignKey``/cascade, since a notification's history
    must survive the workflow it was about being deleted. Both are ``None``
    for a Test Notification, which has no workflow at all.
    """

    __tablename__ = "notification_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    workflow_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    workflow_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
