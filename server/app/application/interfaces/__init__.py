"""Interfaces for infrastructure concerns the application layer depends on.

Every class here is an abstract contract with no concrete implementation yet
(mirrors the reserved-but-empty ``app/auth/``, ``app/storage/`` packages this
repository already uses for capabilities that don't exist yet). They exist now
so future phases (authentication, media storage, notifications, an audit
trail) implement against a stable seam instead of application services being
rewritten to accommodate them later. None of these interfaces are constructed
or injected anywhere today — that wiring begins the day a concrete
implementation exists.
"""

from __future__ import annotations

from app.application.interfaces.audit import AuditRecorder
from app.application.interfaces.clock import Clock
from app.application.interfaces.current_user import CurrentUserProvider
from app.application.interfaces.id_generator import IdGenerator
from app.application.interfaces.notification import NotificationSender
from app.application.interfaces.storage import ObjectStorage
from app.application.interfaces.unit_of_work import UnitOfWork

__all__ = [
    "AuditRecorder",
    "Clock",
    "CurrentUserProvider",
    "IdGenerator",
    "NotificationSender",
    "ObjectStorage",
    "UnitOfWork",
]
