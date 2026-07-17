"""Application DTOs: transport-agnostic shapes independent of any persistence model.

Never construct one of these from a SQLAlchemy model or repository entity
directly (no ``model_validate(orm_object)``); always go through the matching
function in ``app.application.mappers``.
"""

from __future__ import annotations

from app.application.dto.auth_dto import (
    DeviceCredentialDTO,
    DeviceTokenDTO,
    TokenPairDTO,
    UserDTO,
)
from app.application.dto.command_dto import (
    CommandDetailDTO,
    CommandDTO,
    CommandEventDTO,
    CommandPageDTO,
    CommandResultDTO,
)
from app.application.dto.device_dto import CapabilityDTO, DeviceDTO, DevicePageDTO
from app.application.dto.health_dto import HealthStatusDTO, ServiceInfoDTO

__all__ = [
    "CapabilityDTO",
    "CommandDTO",
    "CommandDetailDTO",
    "CommandEventDTO",
    "CommandPageDTO",
    "CommandResultDTO",
    "DeviceCredentialDTO",
    "DeviceDTO",
    "DevicePageDTO",
    "DeviceTokenDTO",
    "HealthStatusDTO",
    "ServiceInfoDTO",
    "TokenPairDTO",
    "UserDTO",
]
