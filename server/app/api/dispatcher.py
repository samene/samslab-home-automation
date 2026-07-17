"""FastAPI delivery adapter for read-only Command Dispatcher admin endpoints.

Contains no business logic: each route only resolves the running
``CommandDispatcher`` singleton from the DI container and returns the DTO
one of its accessor methods produces.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.application.dto.dispatcher_dto import (
    DispatcherQueueItemDTO,
    DispatcherRunningItemDTO,
    DispatcherStatisticsDTO,
    DispatcherStatusDTO,
)
from app.dispatcher.dispatcher import CommandDispatcher
from app.domains.auth.dependencies import RequirePermission

router = APIRouter(prefix="/dispatcher", tags=["Dispatcher"])


def get_dispatcher(request: Request) -> CommandDispatcher:
    """Resolve the shared, per-application Command Dispatcher from the DI container."""
    dispatcher: CommandDispatcher = request.app.state.container.dispatcher()
    return dispatcher


@router.get(
    "/status",
    response_model=DispatcherStatusDTO,
    summary="Report the dispatcher's own run state.",
)
async def get_status(
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
    _principal: object = Depends(RequirePermission("system.admin")),
) -> DispatcherStatusDTO:
    """Read-only snapshot of whether the dispatcher is running and its queue depth."""
    return dispatcher.status()


@router.get(
    "/queue",
    response_model=list[DispatcherQueueItemDTO],
    summary="List commands currently waiting in the in-memory dispatch queue.",
)
async def get_queue(
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
    _principal: object = Depends(RequirePermission("system.admin")),
) -> list[DispatcherQueueItemDTO]:
    """Read-only snapshot of the priority queue, in dispatch order."""
    return dispatcher.queue_snapshot()


@router.get(
    "/running",
    response_model=list[DispatcherRunningItemDTO],
    summary="List commands currently past dispatch (awaiting ack or a result).",
)
async def get_running(
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
    _principal: object = Depends(RequirePermission("system.admin")),
) -> list[DispatcherRunningItemDTO]:
    """Read-only snapshot of commands awaiting acknowledgement or a result."""
    return dispatcher.running_snapshot()


@router.get(
    "/statistics",
    response_model=DispatcherStatisticsDTO,
    summary="Report the dispatcher's own operational counters.",
)
async def get_statistics(
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
    _principal: object = Depends(RequirePermission("system.admin")),
) -> DispatcherStatisticsDTO:
    """Read-only snapshot of dispatch/failure/retry/timeout counters."""
    return dispatcher.statistics()
