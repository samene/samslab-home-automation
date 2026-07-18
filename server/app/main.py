"""FastAPI application factory for the Sam's Lab cloud-server foundation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi import Request as FastAPIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.camera import router as camera_router
from app.api.dispatcher import router as dispatcher_router
from app.api.health import router as health_router
from app.api.mediamtx_jwks import router as mediamtx_jwks_router
from app.application.exceptions import (
    ApplicationError,
    ApplicationValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.config.settings import Settings
from app.core.container import ApplicationContainer, build_container
from app.core.database import Database
from app.core.problems import (
    ProblemDetails,
    http_exception_handler,
    unhandled_exception_handler,
)
from app.domains.auth.api import router as auth_router
from app.domains.commands.api import router as commands_router
from app.domains.devices.api import router as devices_router
from app.domains.snapshots.api import router as snapshots_router
from app.domains.workflows.api import router as workflows_router
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.service import WorkflowService
from app.logging.configure import configure_logging
from app.logging.context import get_request_context
from app.middleware.request_context import RequestContextMiddleware
from app.websocket.router import build_websocket_router


def _openapi_servers(settings: Settings) -> list[dict[str, str]]:
    """Build explicit OpenAPI server metadata for the current deployment environment."""
    return [
        {
            "url": f"http://{settings.host}:{settings.port}",
            "description": f"{settings.environment.value.title()} server",
        }
    ]


async def _reconcile_interrupted_workflow_runs(database: Database) -> None:
    """Fail any ``workflow_runs`` row left RUNNING by a previous process's crash/restart.

    The ``asyncio.Task`` that was driving it does not survive the process,
    even though the DB row does — without this, such a run would show
    "running" forever in the list and live Execution Status views.
    """
    logger = structlog.get_logger("app.lifecycle")
    async with database.session_factory() as session:
        service = WorkflowService(WorkflowRepository(session))
        reconciled_count = await service.reconcile_interrupted_runs()
        await session.commit()
    if reconciled_count:
        logger.warning("workflow_runs_reconciled", count=reconciled_count)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and cleanly release application-owned foundation resources."""
    settings: Settings = app.state.container.settings()
    configure_logging(settings)
    logger = structlog.get_logger("app.lifecycle")
    logger.info("application_starting", server_name=settings.server_name)
    database = app.state.container.database()
    if database is not None:
        await _reconcile_interrupted_workflow_runs(database)
    dispatcher = app.state.container.dispatcher()
    await dispatcher.start()
    try:
        yield
    finally:
        await dispatcher.stop()
        session_manager = app.state.container.session_manager()
        await session_manager.close_all()
        await session_manager.wait_closed()
        workflow_run_registry = app.state.container.workflow_run_registry()
        await workflow_run_registry.wait_closed(timeout=settings.workflow_run_shutdown_wait_seconds)
        if database is not None:
            await database.dispose()
        app.state.container.shutdown_resources()
        logger.info("application_stopped", server_name=settings.server_name)


async def validation_exception_handler(request: FastAPIRequest, _exc: Exception) -> JSONResponse:
    """Render validation failures as RFC 7807 problems without exposing internals."""
    problem = ProblemDetails(
        type="https://samslab.dev/problems/request-validation",
        title="Request Validation Failed",
        status=422,
        detail="The request could not be validated.",
        instance=str(request.url.path),
        trace_id=get_request_context().get("request_id"),
    )
    return JSONResponse(
        content=problem.model_dump(exclude_none=True),
        status_code=422,
        media_type="application/problem+json",
    )


async def application_exception_handler(request: FastAPIRequest, exc: Exception) -> JSONResponse:
    """Map application-layer failures to safe, stable RFC 7807 API problems.

    This is the only place REST maps a failure to a status code, and it only
    ever sees ``ApplicationError`` — never a domain's own exception types.
    Every application service is responsible for translating domain failures
    into one of these categories before they reach this handler.
    """
    error = exc if isinstance(exc, ApplicationError) else ApplicationError(str(exc))
    if isinstance(error, NotFoundError):
        status_code = 404
    elif isinstance(error, ConflictError):
        status_code = 409
    elif isinstance(error, ApplicationValidationError):
        status_code = 422
    elif isinstance(error, ForbiddenError):
        status_code = 403
    elif isinstance(error, UnauthorizedError):
        status_code = 401
    else:
        status_code = 400
    problem = ProblemDetails(
        type=f"https://samslab.dev/problems/{error.__class__.__name__}",
        title=error.__class__.__name__,
        status=status_code,
        detail=str(error),
        instance=str(request.url.path),
        trace_id=get_request_context().get("request_id"),
    )
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        content=problem.model_dump(exclude_none=True),
        status_code=status_code,
        media_type="application/problem+json",
        headers=headers,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a fully isolated FastAPI application instance.

    No module-level application object is created. Tests and production entrypoints each
    call this factory, optionally supplying validated settings for deterministic setup.
    """
    resolved_settings = settings or Settings()
    container: ApplicationContainer = build_container(resolved_settings)
    application = FastAPI(
        title=resolved_settings.server_name,
        description=(
            "Cloud control-plane foundation for Sam's Lab: JWT authentication and RBAC, "
            "the Device Registry, the Command domain, an authenticated WebSocket gateway "
            "for persistent agent connections, and a Command Dispatcher that delivers "
            "commands to connected devices, tracks acknowledgements/results, and retries "
            "transport failures."
        ),
        version="0.1.0",
        contact={"name": "Sam's Lab", "url": "https://github.com/smene/samslab-home-automation"},
        license_info={"name": "Proprietary"},
        servers=_openapi_servers(resolved_settings),
        openapi_tags=[
            {
                "name": "System",
                "description": "Unauthenticated infrastructure health endpoints.",
            },
            {
                "name": "Auth",
                "description": (
                    "JWT authentication and role/permission-based authorization for "
                    "both human users and device (agent) principals."
                ),
            },
            {
                "name": "Devices",
                "description": "Logical compute-node registry; no hardware communication occurs here.",
            },
            {
                "name": "Commands",
                "description": (
                    "Command lifecycle and intent management; the server never talks to "
                    "devices directly. Transport and dispatch are future capabilities."
                ),
            },
            {
                "name": "WebSocket",
                "description": (
                    "Persistent, authenticated agent connections and read-only session "
                    "introspection. Transport only: it does not execute commands or "
                    "access GPIO/repositories directly."
                ),
            },
            {
                "name": "Dispatcher",
                "description": (
                    "Read-only introspection into the Command Dispatcher's background "
                    "delivery pipeline: run status, the in-memory priority queue, "
                    "commands awaiting acknowledgement/results, and operational counters."
                ),
            },
            {
                "name": "Camera",
                "description": (
                    "Live camera stream lifecycle, orchestrated entirely through "
                    "camera.stream.* commands. The browser never talks to the "
                    "Raspberry Pi; it only ever receives a MediaMTX playback URL."
                ),
            },
            {
                "name": "Snapshots",
                "description": (
                    "High-resolution still-image metadata, captured via camera.snapshot "
                    "commands and uploaded directly to Amazon S3 by the agent. The "
                    "backend never proxies image bytes; it only mints fresh, "
                    "short-lived presigned URLs on read."
                ),
            },
            {
                "name": "Workflows",
                "description": (
                    "Ordered, reusable sequences of existing commands (plus pure "
                    "delays), executed serially or in parallel groups entirely "
                    "through the Command Framework. No task ever touches hardware "
                    "directly."
                ),
            },
        ],
        lifespan=lifespan,
    )
    application.state.container = container
    application.add_middleware(RequestContextMiddleware)
    if resolved_settings.allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.allow_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(devices_router)
    application.include_router(commands_router)
    application.include_router(build_websocket_router(resolved_settings))
    application.include_router(dispatcher_router)
    application.include_router(camera_router)
    application.include_router(snapshots_router)
    application.include_router(workflows_router)
    application.include_router(mediamtx_jwks_router)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(ApplicationError, application_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    return application
