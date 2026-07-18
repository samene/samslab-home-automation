"""FastAPI delivery adapter for Workflow definitions and execution.

Contains no business logic: each route only resolves the application
service and returns the DTO it produces. Unlike most domains' ``api.py``,
every route here (including plain CRUD) goes through
``WorkflowApplicationService`` rather than the domain ``WorkflowService``
directly, since ``run_workflow`` needs the application service's
self-managing-session behavior and there is no reason for the CRUD routes
to use a different service than the run route does.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.application.dto.workflow_dto import WorkflowDetailDTO, WorkflowPageDTO
from app.application.events.bus import EventBus
from app.application.services.workflow_service import WorkflowApplicationService
from app.core.database import Database
from app.dependencies import get_database, get_event_bus
from app.domains.workflows.schemas import WorkflowCreate, WorkflowUpdate

router = APIRouter(prefix="/workflows", tags=["Workflows"])


def get_workflow_application_service(
    request: Request,
    database: Database = Depends(get_database),
    event_bus: EventBus = Depends(get_event_bus),
) -> WorkflowApplicationService:
    """Build the Workflow application service; it manages its own sessions per operation.

    Unlike other application services, this one is not bound to one
    request-scoped transaction — see ``WorkflowApplicationService``'s
    docstring for why (mirrors ``get_camera_application_service``).
    """
    settings = request.app.state.container.settings()
    return WorkflowApplicationService(
        database=database,
        event_bus=event_bus,
        run_registry=request.app.state.container.workflow_run_registry(),
        command_timeout_seconds=settings.workflow_command_timeout_seconds,
        command_poll_interval_seconds=settings.workflow_command_poll_interval_seconds,
        s3_client=request.app.state.container.s3_client(),
        presigned_url_ttl_seconds=settings.aws_presigned_url_ttl_seconds,
    )


@router.get("", response_model=WorkflowPageDTO)
async def list_workflows(
    service: WorkflowApplicationService = Depends(get_workflow_application_service),
    offset: int = Query(default=0),
    limit: int = Query(default=50),
) -> WorkflowPageDTO:
    """List active workflows with their denormalized last-run summary."""
    return await service.list_workflows(offset=offset, limit=limit)


@router.get("/{workflow_id}", response_model=WorkflowDetailDTO)
async def get_workflow(
    workflow_id: UUID,
    service: WorkflowApplicationService = Depends(get_workflow_application_service),
) -> WorkflowDetailDTO:
    """Return one workflow's full step tree plus its most recent run."""
    return await service.get_workflow(workflow_id)


@router.post("", response_model=WorkflowDetailDTO, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: WorkflowCreate,
    service: WorkflowApplicationService = Depends(get_workflow_application_service),
) -> WorkflowDetailDTO:
    """Define a new workflow and its full step tree."""
    return await service.create_workflow(request)


@router.put("/{workflow_id}", response_model=WorkflowDetailDTO)
async def update_workflow(
    workflow_id: UUID,
    request: WorkflowUpdate,
    service: WorkflowApplicationService = Depends(get_workflow_application_service),
) -> WorkflowDetailDTO:
    """Replace a workflow's fields and its entire step tree."""
    return await service.update_workflow(workflow_id, request)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    service: WorkflowApplicationService = Depends(get_workflow_application_service),
    delete_artifacts: bool = Query(default=False),
) -> Response:
    """Soft-delete a workflow, optionally hard-deleting the snapshots it generated first."""
    await service.delete_workflow(workflow_id, delete_artifacts=delete_artifacts)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/run", response_model=WorkflowDetailDTO)
async def run_workflow(
    workflow_id: UUID,
    service: WorkflowApplicationService = Depends(get_workflow_application_service),
) -> WorkflowDetailDTO:
    """Trigger a run in the background; returns immediately with it RUNNING."""
    return await service.run_workflow(workflow_id)
