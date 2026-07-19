"""FastAPI delivery adapter for Workflow Schedules.

Contains no business logic: each route only resolves the application
service and returns the DTO it produces. Every route goes through
``ScheduleApplicationService`` rather than the domain ``ScheduleService``
directly — mirroring ``workflows/api.py``'s own reasoning — since create/
update/enable/disable/delete all need to keep the live ``WorkflowScheduler``
in sync, not just the database row.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.application.dto.schedule_dto import (
    ScheduleDTO,
    ScheduleExecutionPageDTO,
    SchedulePageDTO,
)
from app.application.dto.workflow_dto import WorkflowDetailDTO
from app.application.events.bus import EventBus
from app.application.services.schedule_service import ScheduleApplicationService
from app.application.services.workflow_service import WorkflowApplicationService
from app.core.database import Database
from app.dependencies import get_database, get_event_bus
from app.domains.schedules.schemas import ScheduleCreate, ScheduleUpdate

router = APIRouter(prefix="/schedules", tags=["Schedules"])


def get_schedule_application_service(
    request: Request,
    database: Database = Depends(get_database),
    event_bus: EventBus = Depends(get_event_bus),
) -> ScheduleApplicationService:
    """Build the Schedules application service; it manages its own sessions per operation.

    Builds its own ``WorkflowApplicationService`` exactly like
    ``workflows/api.py``'s own dependency function does — this is a second,
    independent instance, not a shared singleton, matching that file's
    existing per-request construction pattern.
    """
    settings = request.app.state.container.settings()
    workflow_app_service = WorkflowApplicationService(
        database=database,
        event_bus=event_bus,
        run_registry=request.app.state.container.workflow_run_registry(),
        command_timeout_seconds=settings.workflow_command_timeout_seconds,
        command_poll_interval_seconds=settings.workflow_command_poll_interval_seconds,
        s3_client=request.app.state.container.s3_client(),
        presigned_url_ttl_seconds=settings.aws_presigned_url_ttl_seconds,
    )
    return ScheduleApplicationService(
        database=database,
        workflow_app_service=workflow_app_service,
        scheduler=request.app.state.container.scheduler(),
        run_registry=request.app.state.container.schedule_run_registry(),
        run_outcome_poll_interval_seconds=settings.scheduler_run_outcome_poll_interval_seconds,
        run_outcome_timeout_seconds=settings.scheduler_run_outcome_timeout_seconds,
        s3_client=request.app.state.container.s3_client(),
        presigned_url_ttl_seconds=settings.aws_presigned_url_ttl_seconds,
    )


@router.get("", response_model=SchedulePageDTO)
async def list_schedules(
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
    enabled: bool | None = Query(default=None),
    workflow_id: UUID | None = Query(default=None),
    offset: int = Query(default=0),
    limit: int = Query(default=50),
) -> SchedulePageDTO:
    """List schedules, soonest next run first — backs both the Schedules page and Dashboard widget."""
    return await service.list_schedules(
        offset=offset, limit=limit, enabled=enabled, workflow_id=workflow_id
    )


@router.get("/executions", response_model=ScheduleExecutionPageDTO)
async def list_schedule_executions(
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
    offset: int = Query(default=0),
    limit: int = Query(default=100),
) -> ScheduleExecutionPageDTO:
    """List every schedule firing, newest first — backs History's Manual/Scheduled correlation.

    Registered before ``/{schedule_id}`` so "executions" is never matched as
    a schedule id.
    """
    return await service.list_executions(offset=offset, limit=limit)


@router.get("/{schedule_id}", response_model=ScheduleDTO)
async def get_schedule(
    schedule_id: UUID,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
) -> ScheduleDTO:
    """Return one schedule with its workflow's current name resolved."""
    return await service.get_schedule(schedule_id)


@router.post("", response_model=ScheduleDTO, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    request: ScheduleCreate,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
) -> ScheduleDTO:
    """Define a new schedule and register it live if enabled."""
    return await service.create_schedule(request)


@router.put("/{schedule_id}", response_model=ScheduleDTO)
async def update_schedule(
    schedule_id: UUID,
    request: ScheduleUpdate,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
) -> ScheduleDTO:
    """Replace a schedule's fields and re-sync its live registration."""
    return await service.update_schedule(schedule_id, request)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
    delete_artifacts: bool = Query(default=False),
) -> Response:
    """Unregister the live job, soft-delete, optionally cascade-deleting everything it produced."""
    await service.delete_schedule(schedule_id, delete_artifacts=delete_artifacts)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{schedule_id}/run", response_model=WorkflowDetailDTO)
async def run_schedule_now(
    schedule_id: UUID,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
) -> WorkflowDetailDTO:
    """Manually trigger the schedule's workflow through the exact same execution path."""
    return await service.run_now(schedule_id)


@router.post("/{schedule_id}/enable", response_model=ScheduleDTO)
async def enable_schedule(
    schedule_id: UUID,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
) -> ScheduleDTO:
    """Enable a schedule and register its live job for immediate effect."""
    return await service.enable_schedule(schedule_id)


@router.post("/{schedule_id}/disable", response_model=ScheduleDTO)
async def disable_schedule(
    schedule_id: UUID,
    service: ScheduleApplicationService = Depends(get_schedule_application_service),
) -> ScheduleDTO:
    """Disable a schedule and unregister its live job for immediate effect."""
    return await service.disable_schedule(schedule_id)
