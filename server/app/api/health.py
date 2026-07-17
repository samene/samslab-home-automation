"""FastAPI delivery adapter for liveness, readiness, and root endpoints.

Contains no business logic: each route only resolves the application
service and returns the DTO it produces.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.application.dto.health_dto import HealthStatusDTO, ServiceInfoDTO
from app.application.services.health_service import HealthApplicationService

router = APIRouter(tags=["System"])


def get_health_application_service(request: Request) -> HealthApplicationService:
    """Build the health application service from the configured server name."""
    return HealthApplicationService(request.app.state.container.settings().server_name)


@router.get("/", response_model=ServiceInfoDTO, summary="Describe this service")
async def root(
    service: HealthApplicationService = Depends(get_health_application_service),
) -> ServiceInfoDTO:
    """Return the configured service name without accessing external dependencies."""
    return service.describe_service()


@router.get("/health", response_model=HealthStatusDTO, summary="Report basic server health")
async def health(
    service: HealthApplicationService = Depends(get_health_application_service),
) -> HealthStatusDTO:
    """Report process health; this intentionally does not check future dependencies."""
    return service.check_health()


@router.get("/ready", response_model=HealthStatusDTO, summary="Report server readiness")
async def ready(
    request: Request,
    response: Response,
    service: HealthApplicationService = Depends(get_health_application_service),
) -> HealthStatusDTO:
    """Report readiness, including whether a started Command Dispatcher is still running."""
    dispatcher = request.app.state.container.dispatcher()
    result = service.check_readiness(dispatcher_healthy=dispatcher.health_ok)
    if result.status != "ok":
        response.status_code = 503
    return result


@router.get("/live", response_model=HealthStatusDTO, summary="Report process liveness")
async def live(
    service: HealthApplicationService = Depends(get_health_application_service),
) -> HealthStatusDTO:
    """Report that the ASGI process can accept requests."""
    return service.check_liveness()
