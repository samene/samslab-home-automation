"""Application service wrapping system health/identity use cases for REST controllers.

There is no "health domain" — these use cases are intentionally trivial and
dependency-free today (see ``docs/architecture/DEPLOYMENT.md``); this service
exists so the health controller follows the same REST -> Application layering
as every other controller, with no shortcut for "simple" endpoints.
"""

from __future__ import annotations

from app.application.dto.health_dto import HealthStatusDTO, ServiceInfoDTO


class HealthApplicationService:
    """Expose liveness/readiness/identity use cases as DTOs."""

    def __init__(self, server_name: str) -> None:
        """Capture the configured server name for the identity use case."""
        self._server_name = server_name

    def describe_service(self) -> ServiceInfoDTO:
        """Return this service's configured identity."""
        return ServiceInfoDTO(service=self._server_name)

    def check_health(self) -> HealthStatusDTO:
        """Report basic process health; no external dependency checks yet."""
        return HealthStatusDTO()

    def check_readiness(self, *, dispatcher_healthy: bool = True) -> HealthStatusDTO:
        """Report readiness, folding in whether a started Command Dispatcher is still running."""
        if not dispatcher_healthy:
            return HealthStatusDTO(status="unhealthy")
        return HealthStatusDTO()

    def check_liveness(self) -> HealthStatusDTO:
        """Report that the process can accept requests."""
        return HealthStatusDTO()
