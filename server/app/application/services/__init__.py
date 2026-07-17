"""Application services: the only thing a REST controller ever depends on.

Each wraps one or more domain services, returns application DTOs, translates
domain exceptions into application exceptions, and — where a cross-domain
rule applies — is the one place that rule is enforced.
"""

from __future__ import annotations

from app.application.services.auth_service import AuthApplicationService
from app.application.services.command_service import CommandApplicationService
from app.application.services.device_service import DeviceApplicationService
from app.application.services.health_service import HealthApplicationService

__all__ = [
    "AuthApplicationService",
    "CommandApplicationService",
    "DeviceApplicationService",
    "HealthApplicationService",
]
