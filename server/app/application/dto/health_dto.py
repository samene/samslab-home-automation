"""Health/system data transfer objects."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthStatusDTO(BaseModel):
    """Minimal status reported by infrastructure health checks."""

    status: Literal["ok", "unhealthy"] = "ok"


class ServiceInfoDTO(HealthStatusDTO):
    """Service identity reported by the root endpoint."""

    service: str
