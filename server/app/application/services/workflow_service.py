"""Application service orchestrating Workflow execution through the Command Framework.

There is no separate execution "engine"/Job class — this service is the one
executable orchestrator, exactly like ``CameraApplicationService`` is for
camera commands. Every method opens its own short-lived session
(``_build_workflow_service``/``_build_command_service``/``_build_device_service``,
mirroring Camera's own per-operation session helpers) rather than holding a
single request-scoped session, because ``run_workflow`` has to detach its
wait from the HTTP request entirely: a workflow can run far longer than one
request should ever block for. ``run_workflow`` creates the ``workflow_run``
row, hands the execution coroutine to a ``WorkflowRunRegistry`` (tracked so
``app/main.py``'s lifespan can wait for it on shutdown), and returns
immediately with the run in ``RUNNING`` status — the caller polls
``get_workflow`` afterward to observe progress via its embedded
``latest_run``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.command_dto import CommandDetailDTO
from app.application.dto.workflow_dto import WorkflowDetailDTO, WorkflowPageDTO
from app.application.events.bus import EventBus
from app.application.exceptions import (
    WorkflowDeviceNotFoundError,
    WorkflowDisabledError,
    WorkflowStepFailedError,
    WorkflowStepTimedOutError,
    translate_domain_error,
)
from app.application.mappers.workflow_mapper import to_workflow_detail_dto, to_workflow_dto
from app.application.services.command_artifacts import record_snapshot_from_command
from app.application.services.command_service import CommandApplicationService
from app.application.services.device_service import DeviceApplicationService
from app.application.services.snapshot_service import SnapshotApplicationService
from app.application.services.workflow_run_registry import WorkflowRunRegistry
from app.application.validators import PaginationParams
from app.core.database import Database
from app.core.s3_client import S3Client
from app.domains.commands.models import TERMINAL_STATUSES, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.service import DeviceService
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService
from app.domains.workflows.exceptions import WorkflowDomainError
from app.domains.workflows.models import (
    WorkflowGroupMode,
    WorkflowRunStatus,
    WorkflowStep,
    WorkflowStepRunStatus,
    WorkflowStepType,
)
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.schemas import WorkflowCreate, WorkflowUpdate
from app.domains.workflows.service import WorkflowService

logger = structlog.get_logger(__name__)

_ROOT_PARENT_STEP_ID = None


class WorkflowApplicationService:
    """Expose Workflow CRUD and `run` use cases as DTOs, translating domain failures."""

    def __init__(
        self,
        *,
        database: Database,
        event_bus: EventBus,
        run_registry: WorkflowRunRegistry,
        command_timeout_seconds: float,
        command_poll_interval_seconds: float,
        s3_client: S3Client | None = None,
        presigned_url_ttl_seconds: float = 300.0,
    ) -> None:
        """Bind to the shared database/event bus/run registry and command polling config.

        ``s3_client``/``presigned_url_ttl_seconds`` are only ever used by
        ``delete_workflow(delete_artifacts=True)``, to reuse
        ``SnapshotApplicationService.delete_snapshot``'s existing S3-cleanup
        logic rather than duplicating it.
        """
        self._database = database
        self._event_bus = event_bus
        self._run_registry = run_registry
        self._command_timeout_seconds = command_timeout_seconds
        self._command_poll_interval_seconds = command_poll_interval_seconds
        self._s3_client = s3_client
        self._presigned_url_ttl_seconds = presigned_url_ttl_seconds

    # --- CRUD ---------------------------------------------------------------

    async def list_workflows(self, *, offset: int, limit: int) -> WorkflowPageDTO:
        """List workflows with bounded, centrally validated pagination."""
        pagination = PaginationParams.create(offset=offset, limit=limit)
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            workflows, total = await service.list_workflows(
                offset=pagination.offset, limit=pagination.limit
            )
            page = WorkflowPageDTO(
                items=[to_workflow_dto(workflow) for workflow in workflows],
                total=total,
                offset=pagination.offset,
                limit=pagination.limit,
            )
            await session.commit()
            return page

    async def get_workflow(self, workflow_id: UUID) -> WorkflowDetailDTO:
        """Return one workflow's full definition plus its most recent run."""
        return await self._get_workflow_detail(workflow_id)

    async def create_workflow(self, request: WorkflowCreate) -> WorkflowDetailDTO:
        """Persist a new workflow and return its full detail."""
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            workflow = await service.register_workflow(request)
            workflow_id = workflow.id
            await session.commit()
        return await self._get_workflow_detail(workflow_id)

    async def update_workflow(self, workflow_id: UUID, request: WorkflowUpdate) -> WorkflowDetailDTO:
        """Replace a workflow's fields and its entire step tree."""
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            try:
                await service.update_workflow(workflow_id, request)
            except WorkflowDomainError as error:
                raise translate_domain_error(error) from error
            await session.commit()
        return await self._get_workflow_detail(workflow_id)

    async def delete_workflow(self, workflow_id: UUID, *, delete_artifacts: bool = False) -> None:
        """Soft-delete a workflow, optionally hard-deleting everything it generated first.

        Snapshots aren't touched by default — a workflow's run history and
        the images it produced are independently useful even after the
        workflow definition itself is gone. When ``delete_artifacts`` is
        true, every ``Snapshot`` this workflow's runs ever produced is
        deleted first (S3 objects best-effort, row hard-deleted), reusing
        ``SnapshotApplicationService.delete_snapshot`` rather than
        duplicating its S3-cleanup logic.
        """
        if delete_artifacts:
            for snapshot_id in await self._find_generated_snapshot_ids(workflow_id):
                await self._delete_snapshot(snapshot_id)
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            try:
                await service.delete(workflow_id)
            except WorkflowDomainError as error:
                raise translate_domain_error(error) from error
            await session.commit()

    async def _find_generated_snapshot_ids(self, workflow_id: UUID) -> list[UUID]:
        async with self._database.session_factory() as session:
            snapshots = await SnapshotService(SnapshotRepository(session)).find_by_workflow_id(
                workflow_id
            )
            await session.commit()
            return [snapshot.id for snapshot in snapshots]

    async def _delete_snapshot(self, snapshot_id: UUID) -> None:
        async with self._database.session_factory() as session:
            service = SnapshotApplicationService(
                SnapshotService(SnapshotRepository(session)),
                s3_client=self._s3_client,
                presigned_url_ttl_seconds=self._presigned_url_ttl_seconds,
            )
            await service.delete_snapshot(snapshot_id)
            await session.commit()

    # --- Execution ------------------------------------------------------------

    async def run_workflow(self, workflow_id: UUID) -> WorkflowDetailDTO:
        """Start a run in the background and return immediately with it RUNNING.

        The caller observes progress by polling ``get_workflow`` — its
        embedded ``latest_run`` reflects live per-step status as the
        detached task below progresses.
        """
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            try:
                workflow = await service.get_workflow(workflow_id)
            except WorkflowDomainError as error:
                raise translate_domain_error(error) from error
            if not workflow.enabled:
                raise WorkflowDisabledError(f"Workflow '{workflow_id}' is disabled")
            steps = await service.get_workflow_steps(workflow_id)
            run = await service.create_run(workflow_id)
            run_id = run.id
            await session.commit()

        task = asyncio.create_task(self._execute_run(workflow_id, run_id, steps))
        self._run_registry.track(task)
        return await self._get_workflow_detail(workflow_id)

    async def _execute_run(
        self, workflow_id: UUID, run_id: UUID, steps: list[WorkflowStep]
    ) -> None:
        """Walk the top-level step list serially; abort the whole run on any failure."""
        try:
            await self._execute_step_list(run_id, steps, parent_step_id=_ROOT_PARENT_STEP_ID)
        except Exception as error:
            logger.warning("workflow_run_failed", workflow_id=str(workflow_id), run_id=str(run_id), error=str(error))
            await self._finish_run(run_id, status=WorkflowRunStatus.FAILED, error_message=str(error))
            return
        await self._finish_run(run_id, status=WorkflowRunStatus.COMPLETED)

    async def _execute_step_list(
        self, run_id: UUID, steps: list[WorkflowStep], *, parent_step_id: UUID | None
    ) -> None:
        """Execute this parent's direct children in order — that's what "serial" means."""
        children = sorted(
            (step for step in steps if step.parent_step_id == parent_step_id),
            key=lambda step: step.position,
        )
        for step in children:
            await self._execute_step(run_id, steps, step)

    async def _execute_step(self, run_id: UUID, all_steps: list[WorkflowStep], step: WorkflowStep) -> None:
        """Execute one step, recording its own step-run row throughout."""
        step_run_id = await self._start_step_run(run_id, step.id)
        try:
            if step.step_type is WorkflowStepType.COMMAND:
                await self._execute_command_step(run_id, step_run_id, step)
            elif step.step_type is WorkflowStepType.SLEEP:
                assert step.sleep_seconds is not None  # enforced by WorkflowStepCreate
                await asyncio.sleep(step.sleep_seconds)
            elif step.step_type is WorkflowStepType.GROUP:
                children = [child for child in all_steps if child.parent_step_id == step.id]
                if step.group_mode is WorkflowGroupMode.PARALLEL:
                    await self._execute_parallel_group(run_id, all_steps, children)
                else:
                    await self._execute_step_list(run_id, all_steps, parent_step_id=step.id)
        except asyncio.CancelledError:
            await self._finish_step_run(step_run_id, status=WorkflowStepRunStatus.CANCELLED)
            raise
        except Exception as error:
            await self._finish_step_run(
                step_run_id, status=WorkflowStepRunStatus.FAILED, error_message=str(error)
            )
            raise
        else:
            await self._finish_step_run(step_run_id, status=WorkflowStepRunStatus.COMPLETED)

    async def _execute_parallel_group(
        self, run_id: UUID, all_steps: list[WorkflowStep], children: list[WorkflowStep]
    ) -> None:
        """Start every child together; wait until ALL complete successfully before continuing.

        Plain ``asyncio.gather`` does *not* cancel sibling awaitables just
        because one of them raised — that only happens for
        ``asyncio.TaskGroup``, or if the ``gather()`` call itself is
        cancelled from outside. Each child therefore runs as its own
        explicit ``asyncio.Task``; the moment any one fails, the rest are
        cancelled and awaited here, so each sibling's own ``_execute_step``
        gets the chance to catch that ``CancelledError`` and mark its
        step-run ``CANCELLED`` (see decision on parallel cancellation)
        instead of being silently orphaned to keep running — possibly all
        the way to its own much-later command timeout — after this group,
        and the whole run, have already gone FAILED.
        """
        ordered = sorted(children, key=lambda step: step.position)
        tasks = [
            asyncio.create_task(self._execute_step(run_id, all_steps, child)) for child in ordered
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        first_error: BaseException | None = None
        for task in done:
            if task.cancelled():
                continue
            error = task.exception()
            if error is not None and first_error is None:
                first_error = error
        if first_error is not None:
            raise first_error

    async def _execute_command_step(self, run_id: UUID, step_run_id: UUID, step: WorkflowStep) -> None:
        assert step.command_type is not None  # enforced by WorkflowStepCreate
        device_id = await self._require_primary_device_id()
        command_id = await self._create_command(device_id, step.command_type, correlation_id=run_id)
        await self._attach_command_to_step_run(step_run_id, command_id)
        try:
            completed = await self._wait_for_terminal(command_id)
        except asyncio.CancelledError:
            await self._cancel_command(command_id)
            raise
        # Treated exactly like any other completed command — the same
        # shared helper CameraApplicationService.capture_snapshot uses,
        # never a snapshot-specific branch in this generic step executor.
        result = completed.result.result if completed.result else {}
        await record_snapshot_from_command(
            self._database,
            command_type=step.command_type,
            device_id=device_id,
            command_id=command_id,
            result=result,
            workflow_run_id=run_id,
        )

    # --- private: session-scoped helpers, mirroring CameraApplicationService ---

    def _build_workflow_service(self, session: AsyncSession) -> WorkflowService:
        return WorkflowService(WorkflowRepository(session))

    def _build_command_service(self, session: AsyncSession) -> CommandApplicationService:
        return CommandApplicationService(
            CommandService(CommandRepository(session)),
            DeviceService(DeviceRepository(session)),
            self._event_bus,
        )

    def _build_device_service(self, session: AsyncSession) -> DeviceApplicationService:
        return DeviceApplicationService(DeviceService(DeviceRepository(session)), self._event_bus)

    async def _require_primary_device_id(self) -> UUID:
        """Return the single MVP device's id, or raise if none is registered.

        Deliberately duplicated (not imported) from
        ``CameraApplicationService``'s identical private method, to keep
        this feature's changes isolated from an already-shipped file — see
        ``docs/architecture/WORKFLOWS.md`` for the note on unifying them later.
        """
        async with self._database.session_factory() as session:
            service = self._build_device_service(session)
            page = await service.list_devices(
                status=None, enabled=None, capability=None, search=None, offset=0, limit=1
            )
            await session.commit()
        if not page.items:
            raise WorkflowDeviceNotFoundError("No registered device available to run this workflow")
        return page.items[0].id

    async def _create_command(
        self, device_id: UUID, command_type: str, *, correlation_id: UUID
    ) -> UUID:
        """Create and commit a command so other sessions/processes can see it immediately."""
        async with self._database.session_factory() as session:
            service = self._build_command_service(session)
            command = await service.create_command(
                CommandCreate(
                    device_id=device_id, command_type=command_type, correlation_id=correlation_id
                )
            )
            await session.commit()
            return command.id

    async def _get_command(self, command_id: UUID) -> CommandDetailDTO:
        """Fetch a command in its own fresh transaction, so it sees other sessions' commits."""
        async with self._database.session_factory() as session:
            service = self._build_command_service(session)
            command = await service.get_command(command_id)
            await session.commit()
            return command

    async def _cancel_command(self, command_id: UUID) -> None:
        """Best-effort: a parallel sibling's failure cancelling this command must never blow up."""
        try:
            async with self._database.session_factory() as session:
                service = self._build_command_service(session)
                await service.cancel_command(command_id, reason="workflow run cancelled")
                await session.commit()
        except Exception as error:
            logger.warning(
                "workflow_command_cancel_failed", command_id=str(command_id), error=str(error)
            )

    async def _wait_for_terminal(self, command_id: UUID) -> CommandDetailDTO:
        """Poll a command until it reaches a terminal state, or raise once the wait expires."""
        deadline = time.monotonic() + self._command_timeout_seconds
        while True:
            command = await self._get_command(command_id)
            if command.status in TERMINAL_STATUSES:
                if command.status != CommandStatus.COMPLETED:
                    raise WorkflowStepFailedError(
                        f"Command {command_id} ended in status {command.status}"
                    )
                return command
            if time.monotonic() >= deadline:
                raise WorkflowStepTimedOutError(
                    f"Command {command_id} did not complete within {self._command_timeout_seconds}s"
                )
            await asyncio.sleep(self._command_poll_interval_seconds)

    async def _start_step_run(self, run_id: UUID, step_id: UUID) -> UUID:
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            step_run = await service.start_step_run(run_id, step_id)
            await session.commit()
            return step_run.id

    async def _attach_command_to_step_run(self, step_run_id: UUID, command_id: UUID) -> None:
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            await service.attach_command_to_step_run(step_run_id, command_id)
            await session.commit()

    async def _finish_step_run(
        self,
        step_run_id: UUID,
        *,
        status: WorkflowStepRunStatus,
        error_message: str | None = None,
    ) -> None:
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            await service.finish_step_run(step_run_id, status=status, error_message=error_message)
            await session.commit()

    async def _finish_run(
        self, run_id: UUID, *, status: WorkflowRunStatus, error_message: str | None = None
    ) -> None:
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            await service.finish_run(run_id, status=status, error_message=error_message)
            await session.commit()

    async def _get_workflow_detail(self, workflow_id: UUID) -> WorkflowDetailDTO:
        async with self._database.session_factory() as session:
            service = self._build_workflow_service(session)
            try:
                workflow = await service.get_workflow(workflow_id)
            except WorkflowDomainError as error:
                raise translate_domain_error(error) from error
            steps = await service.get_workflow_steps(workflow_id)
            latest_run, latest_run_step_runs = await service.get_latest_run_with_step_runs(
                workflow_id
            )
            await session.commit()
            return to_workflow_detail_dto(
                workflow,
                steps,
                latest_run=latest_run,
                latest_run_step_runs=latest_run_step_runs,
            )
