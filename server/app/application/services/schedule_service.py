"""Application service orchestrating Workflow Schedules.

A Schedule is purely a trigger: every business rule about *how* a workflow
runs already lives in ``WorkflowApplicationService`` (untouched by this
file) — this service only ever calls ``run_workflow(workflow_id)``, exactly
the call "Run Now" makes, whether firing came from a live cron/one-time
trigger (``execute_schedule``, the ``on_fire`` callback body) or a manual
``run_now``. It owns: CRUD, keeping the live ``WorkflowScheduler``'s
registration in sync with the database (register/unregister happen
synchronously inside the same request that mutates ``enabled``/the trigger
fields, for immediate effect — see ``docs`` note in the plan for why this is
push, not poll, unlike the Command Dispatcher), and cascade-delete.

Cascade-delete is the one place this service deliberately reaches into the
Workflow Engine's and Command Framework's own ORM models directly (``Command``,
``WorkflowRun``, ``WorkflowStepRun``) with narrowly-scoped, primary-key-bound
queries, rather than adding a new method to either domain's repository — a
documented exception, chosen specifically because those domains' own files
must never be modified for this feature. Every other cross-domain need
(resolving a workflow's name, deleting a Snapshot, deleting a terminal
Command) reuses an already-existing, already-tested public method exactly
as-is (``WorkflowService.get_workflow_names``, ``SnapshotApplicationService.
delete_snapshot``, ``CommandService.delete_command``).
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.schedule_dto import (
    ScheduleDTO,
    ScheduleExecutionPageDTO,
    SchedulePageDTO,
)
from app.application.dto.workflow_dto import WorkflowDetailDTO
from app.application.exceptions import (
    ApplicationError,
    ScheduleWorkflowNotFoundError,
    translate_domain_error,
)
from app.application.mappers.schedule_mapper import to_schedule_dto, to_schedule_execution_dto
from app.application.services.schedule_run_registry import ScheduleRunRegistry
from app.application.services.snapshot_service import SnapshotApplicationService
from app.application.services.workflow_service import WorkflowApplicationService
from app.application.validators import PaginationParams
from app.core.database import Database
from app.core.s3_client import S3Client
from app.domains.commands.exceptions import CommandDomainError
from app.domains.commands.models import TERMINAL_STATUSES, Command
from app.domains.commands.repository import CommandRepository
from app.domains.commands.service import CommandService
from app.domains.schedules.exceptions import ScheduleDomainError
from app.domains.schedules.models import ScheduleRunStatus, ScheduleType
from app.domains.schedules.repository import ScheduleRepository
from app.domains.schedules.schemas import ScheduleCreate, ScheduleUpdate
from app.domains.schedules.service import ScheduleService
from app.domains.snapshots.models import Snapshot
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService
from app.domains.workflows.exceptions import WorkflowDomainError, WorkflowNotFound
from app.domains.workflows.models import WorkflowRun, WorkflowRunStatus, WorkflowStepRun
from app.domains.workflows.repository import WorkflowRepository
from app.domains.workflows.service import WorkflowService
from app.scheduler.interfaces import SchedulerPort
from app.scheduler.metrics import (
    ENABLED_SCHEDULES,
    SCHEDULE_EXECUTIONS_TOTAL,
    SCHEDULE_FAILURES_TOTAL,
    SCHEDULES_TOTAL,
)

logger = structlog.get_logger(__name__)


class ScheduleApplicationService:
    """Expose Schedule CRUD and firing use cases as DTOs, translating domain failures."""

    def __init__(
        self,
        *,
        database: Database,
        workflow_app_service: WorkflowApplicationService,
        scheduler: SchedulerPort,
        run_registry: ScheduleRunRegistry,
        run_outcome_poll_interval_seconds: float = 0.5,
        run_outcome_timeout_seconds: float = 300.0,
        s3_client: S3Client | None = None,
        presigned_url_ttl_seconds: float = 300.0,
    ) -> None:
        """Bind to shared infrastructure plus the already-built Workflow application service.

        ``s3_client``/``presigned_url_ttl_seconds`` exist only to reuse
        ``SnapshotApplicationService.delete_snapshot``'s S3-cleanup logic for
        cascade-delete, exactly like ``WorkflowApplicationService`` already does.
        """
        self._database = database
        self._workflow_app_service = workflow_app_service
        self._scheduler = scheduler
        self._run_registry = run_registry
        self._run_outcome_poll_interval_seconds = run_outcome_poll_interval_seconds
        self._run_outcome_timeout_seconds = run_outcome_timeout_seconds
        self._s3_client = s3_client
        self._presigned_url_ttl_seconds = presigned_url_ttl_seconds

    # --- CRUD ---------------------------------------------------------------

    async def list_schedules(
        self, *, offset: int, limit: int, enabled: bool | None, workflow_id: UUID | None
    ) -> SchedulePageDTO:
        """List schedules, soonest next run first, bounded pagination."""
        pagination = PaginationParams.create(offset=offset, limit=limit)
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            schedules, total = await service.list_schedules(
                offset=pagination.offset,
                limit=pagination.limit,
                enabled=enabled,
                workflow_id=workflow_id,
            )
            await session.commit()
        workflow_names = await self._resolve_workflow_names([s.workflow_id for s in schedules])
        return SchedulePageDTO(
            items=[to_schedule_dto(s, workflow_name=workflow_names.get(s.workflow_id)) for s in schedules],
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    async def get_schedule(self, schedule_id: UUID) -> ScheduleDTO:
        """Return one schedule with its workflow's current name resolved."""
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            try:
                schedule = await service.get_schedule(schedule_id)
            except ScheduleDomainError as error:
                raise translate_domain_error(error) from error
            await session.commit()
        workflow_names = await self._resolve_workflow_names([schedule.workflow_id])
        return to_schedule_dto(schedule, workflow_name=workflow_names.get(schedule.workflow_id))

    async def create_schedule(self, request: ScheduleCreate) -> ScheduleDTO:
        """Persist a new schedule, then register it live if enabled."""
        await self._require_workflow_exists(request.workflow_id)
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            schedule = await service.register_schedule(request)
            schedule_id = schedule.id
            await session.commit()
        await self._sync_live_registration(schedule_id)
        await self._refresh_schedule_gauges()
        return await self.get_schedule(schedule_id)

    async def update_schedule(self, schedule_id: UUID, request: ScheduleUpdate) -> ScheduleDTO:
        """Replace a schedule's fields, then re-sync its live registration."""
        await self._require_workflow_exists(request.workflow_id)
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            try:
                await service.update_schedule(schedule_id, request)
            except ScheduleDomainError as error:
                raise translate_domain_error(error) from error
            await session.commit()
        await self._sync_live_registration(schedule_id)
        await self._refresh_schedule_gauges()
        return await self.get_schedule(schedule_id)

    async def enable_schedule(self, schedule_id: UUID) -> ScheduleDTO:
        """Enable a schedule and register its live job for immediate effect."""
        return await self._set_enabled(schedule_id, enabled=True)

    async def disable_schedule(self, schedule_id: UUID) -> ScheduleDTO:
        """Disable a schedule and unregister its live job for immediate effect."""
        return await self._set_enabled(schedule_id, enabled=False)

    async def _set_enabled(self, schedule_id: UUID, *, enabled: bool) -> ScheduleDTO:
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            try:
                await service.set_enabled(schedule_id, enabled=enabled)
            except ScheduleDomainError as error:
                raise translate_domain_error(error) from error
            await session.commit()
        await self._sync_live_registration(schedule_id)
        await self._refresh_schedule_gauges()
        return await self.get_schedule(schedule_id)

    async def delete_schedule(self, schedule_id: UUID, *, delete_artifacts: bool = False) -> None:
        """Unregister the live job, optionally cascade-delete everything it ever produced.

        Snapshots/Commands/Workflow executions aren't touched by default —
        a schedule's firing history and what it produced are independently
        useful even after the schedule itself is gone (matches
        ``WorkflowApplicationService.delete_workflow``'s own default).
        """
        self._scheduler.unregister(schedule_id)
        if delete_artifacts:
            await self._delete_generated_artifacts(schedule_id)
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            try:
                await service.delete(schedule_id)
            except ScheduleDomainError as error:
                raise translate_domain_error(error) from error
            await session.commit()
        await self._refresh_schedule_gauges()

    # --- Firing ---------------------------------------------------------------

    async def run_now(self, schedule_id: UUID) -> WorkflowDetailDTO:
        """Manually trigger the schedule's workflow — identical to the Workflows page's Run Now.

        Deliberately skips ``run_count``/``last_run_at``/``schedule_executions``
        bookkeeping: this is a manual trigger (``execution_source=MANUAL``),
        not a scheduled firing, mirroring how pressing Run Now on the
        Workflows page itself never touches a Schedule's own state.
        """
        dto = await self.get_schedule(schedule_id)
        return await self._workflow_app_service.run_workflow(dto.workflow_id)

    async def execute_schedule(self, schedule_id: UUID) -> None:
        """The live scheduler's ``on_fire`` callback body — a schedule actually firing."""
        started = time.monotonic()
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            try:
                schedule = await service.get_schedule(schedule_id)
            except ScheduleDomainError:
                self._scheduler.unregister(schedule_id)
                return
            await session.commit()
        if not schedule.enabled:
            # Raced against a just-disabled schedule; defensively unregister
            # and skip rather than fire something the user just turned off.
            self._scheduler.unregister(schedule_id)
            return

        try:
            detail = await self._workflow_app_service.run_workflow(schedule.workflow_id)
        except ApplicationError as error:
            await self._record_firing(
                schedule_id,
                workflow_id=schedule.workflow_id,
                workflow_run_id=None,
                status=ScheduleRunStatus.FAILED,
                error_message=str(error),
            )
            SCHEDULE_FAILURES_TOTAL.inc()
            logger.warning(
                "schedule_fire_failed",
                schedule_id=str(schedule_id),
                workflow_id=str(schedule.workflow_id),
                error=str(error),
                execution_source="SCHEDULE",
            )
            return

        run_id = detail.latest_run.id if detail.latest_run else None
        await self._record_firing(
            schedule_id,
            workflow_id=schedule.workflow_id,
            workflow_run_id=run_id,
            status=ScheduleRunStatus.RUNNING,
        )
        SCHEDULE_EXECUTIONS_TOTAL.inc()
        logger.info(
            "schedule_fired",
            schedule_id=str(schedule_id),
            workflow_id=str(schedule.workflow_id),
            workflow_run_id=str(run_id) if run_id else None,
            cron_expression=schedule.cron_expression,
            run_at=schedule.run_at.isoformat() if schedule.run_at else None,
            execution_source="SCHEDULE",
            trigger_duration_seconds=round(time.monotonic() - started, 3),
        )

        if schedule.schedule_type is ScheduleType.ONE_TIME:
            await self._auto_disable_after_one_time_fire(schedule_id)

        if run_id is not None:
            task = asyncio.create_task(self._track_run_outcome(schedule_id, run_id))
            self._run_registry.track(task)

    async def list_executions(self, *, offset: int, limit: int) -> ScheduleExecutionPageDTO:
        """List every schedule firing across all schedules, newest first.

        Backs History's "Manual vs Scheduled" correlation: the frontend
        fetches this once and matches each ``workflow_run_id`` against a
        command's own ``correlation_id`` — no change to the Command
        Framework's schema or API needed for that.
        """
        pagination = PaginationParams.create(offset=offset, limit=limit)
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            executions, total = await service.list_all_executions(
                offset=pagination.offset, limit=pagination.limit
            )
            await session.commit()
        schedule_names = await self._resolve_schedule_names([e.schedule_id for e in executions])
        return ScheduleExecutionPageDTO(
            items=[
                to_schedule_execution_dto(e, schedule_name=schedule_names.get(e.schedule_id))
                for e in executions
            ],
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
        )

    # --- private: live-registration sync ---------------------------------------

    async def _sync_live_registration(self, schedule_id: UUID) -> None:
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            schedule = await service.get_schedule(schedule_id)
            if schedule.enabled:
                self._scheduler.register(schedule)
                next_run = self._scheduler.next_run_time(schedule_id)
                await service.set_next_run_at(schedule_id, next_run)
            else:
                self._scheduler.unregister(schedule_id)
                await service.set_next_run_at(schedule_id, None)
            await session.commit()

    async def _record_firing(
        self,
        schedule_id: UUID,
        *,
        workflow_id: UUID,
        workflow_run_id: UUID | None,
        status: ScheduleRunStatus,
        error_message: str | None = None,
    ) -> None:
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            next_run = self._scheduler.next_run_time(schedule_id)
            await service.record_firing(
                schedule_id,
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
                status=status,
                next_run_at=next_run,
                error_message=error_message,
            )
            await session.commit()

    async def _auto_disable_after_one_time_fire(self, schedule_id: UUID) -> None:
        """A DateTrigger job cannot fire twice — keep the DB row consistent with that."""
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            await service.set_enabled(schedule_id, enabled=False)
            await session.commit()
        self._scheduler.unregister(schedule_id)
        await self._refresh_schedule_gauges()

    async def _track_run_outcome(self, schedule_id: UUID, run_id: UUID) -> None:
        """Poll the triggered run until terminal, then reflect its real outcome.

        Uses the Workflow domain's own already-public ``get_run`` (a plain
        read), the same way ``_wait_for_terminal`` elsewhere in this codebase
        polls a command — never touching workflow execution itself. If
        interrupted by a restart, ``last_status`` simply stays at its
        last-known value (``RUNNING``); the source of truth remains the
        ``WorkflowRun`` row, visible through the existing Workflow UI.
        """
        deadline = time.monotonic() + self._run_outcome_timeout_seconds
        while time.monotonic() < deadline:
            async with self._database.session_factory() as session:
                workflow_service = WorkflowService(WorkflowRepository(session))
                try:
                    run = await workflow_service.get_run(run_id)
                except WorkflowNotFound:
                    return
                await session.commit()
            if run.status != WorkflowRunStatus.RUNNING:
                status = (
                    ScheduleRunStatus.COMPLETED
                    if run.status == WorkflowRunStatus.COMPLETED
                    else ScheduleRunStatus.FAILED
                )
                await self._finalize_execution(schedule_id, run_id, status)
                return
            await asyncio.sleep(self._run_outcome_poll_interval_seconds)
        logger.info(
            "schedule_run_outcome_poll_timed_out",
            schedule_id=str(schedule_id),
            workflow_run_id=str(run_id),
        )

    async def _finalize_execution(
        self, schedule_id: UUID, run_id: UUID, status: ScheduleRunStatus
    ) -> None:
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            executions = await service.find_executions_by_schedule_id(schedule_id)
            matching = next((e for e in executions if e.workflow_run_id == run_id), None)
            if matching is not None:
                await service.update_execution_status(matching.id, status=status)
            await service.update_last_status(schedule_id, status=status)
            await session.commit()
        logger.info(
            "schedule_run_outcome_resolved",
            schedule_id=str(schedule_id),
            workflow_run_id=str(run_id),
            status=str(status),
        )

    # --- private: cascade-delete (see module docstring for why raw queries) ----

    async def _delete_generated_artifacts(self, schedule_id: UUID) -> None:
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            executions = await service.find_executions_by_schedule_id(schedule_id)
            run_ids = [e.workflow_run_id for e in executions if e.workflow_run_id is not None]
            # schedule_executions.workflow_run_id has a real FK to workflow_runs.id
            # (no ON DELETE CASCADE, per this codebase's cross-domain convention) —
            # it must be cleared before a WorkflowRun row can be deleted, so this
            # happens here, before _delete_workflow_run below, not afterward.
            await service.delete_executions(schedule_id)
            await session.commit()
        for run_id in run_ids:
            await self._delete_snapshots_for_run(run_id)
            await self._delete_commands_for_run(run_id)
            await self._delete_workflow_run(run_id)

    async def _delete_snapshots_for_run(self, run_id: UUID) -> None:
        async with self._database.session_factory() as session:
            result = await session.execute(
                select(Snapshot.id).where(Snapshot.workflow_run_id == run_id)
            )
            snapshot_ids = list(result.scalars())
            await session.commit()
        for snapshot_id in snapshot_ids:
            async with self._database.session_factory() as session:
                snapshot_app_service = SnapshotApplicationService(
                    SnapshotService(SnapshotRepository(session)),
                    s3_client=self._s3_client,
                    presigned_url_ttl_seconds=self._presigned_url_ttl_seconds,
                )
                try:
                    await snapshot_app_service.delete_snapshot(snapshot_id)
                except ApplicationError as error:
                    logger.warning(
                        "schedule_cascade_snapshot_delete_failed",
                        snapshot_id=str(snapshot_id),
                        error=str(error),
                    )
                await session.commit()

    async def _delete_commands_for_run(self, run_id: UUID) -> None:
        async with self._database.session_factory() as session:
            result = await session.execute(
                select(Command.id, Command.status).where(
                    Command.correlation_id == run_id, Command.deleted_at.is_(None)
                )
            )
            rows = result.all()
            await session.commit()
        for command_id, status in rows:
            if status not in TERMINAL_STATUSES:
                logger.warning(
                    "schedule_cascade_skipped_non_terminal_command",
                    command_id=str(command_id),
                    status=str(status),
                )
                continue
            async with self._database.session_factory() as session:
                command_service = CommandService(CommandRepository(session))
                try:
                    await command_service.delete_command(command_id)
                except CommandDomainError as error:
                    logger.warning(
                        "schedule_cascade_command_delete_failed",
                        command_id=str(command_id),
                        error=str(error),
                    )
                await session.commit()

    async def _delete_workflow_run(self, run_id: UUID) -> None:
        """Deliberately raw: no delete method exists for these rows, and the Workflow
        Engine's own files must never be modified to add one — see module docstring."""
        async with self._database.session_factory() as session:
            await session.execute(
                delete(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == run_id)
            )
            await session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
            await session.commit()

    # --- private: shared helpers -------------------------------------------

    def _build_schedule_service(self, session: AsyncSession) -> ScheduleService:
        return ScheduleService(ScheduleRepository(session))

    async def _require_workflow_exists(self, workflow_id: UUID) -> None:
        async with self._database.session_factory() as session:
            workflow_service = WorkflowService(WorkflowRepository(session))
            try:
                await workflow_service.get_workflow(workflow_id)
            except WorkflowDomainError as error:
                raise ScheduleWorkflowNotFoundError(
                    f"Workflow '{workflow_id}' was not found"
                ) from error
            await session.commit()

    async def _resolve_workflow_names(self, workflow_ids: list[UUID]) -> dict[UUID, str]:
        unique_ids = list({w for w in workflow_ids})
        if not unique_ids:
            return {}
        async with self._database.session_factory() as session:
            workflow_service = WorkflowService(WorkflowRepository(session))
            names = await workflow_service.get_workflow_names(unique_ids)
            await session.commit()
            return names

    async def _resolve_schedule_names(self, schedule_ids: list[UUID]) -> dict[UUID, str]:
        unique_ids = list({s for s in schedule_ids})
        if not unique_ids:
            return {}
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            names = await service.get_schedule_names(unique_ids)
            await session.commit()
            return names

    async def _refresh_schedule_gauges(self) -> None:
        async with self._database.session_factory() as session:
            service = self._build_schedule_service(session)
            _, total = await service.list_schedules(
                offset=0, limit=1, enabled=None, workflow_id=None
            )
            _, enabled_total = await service.list_schedules(
                offset=0, limit=1, enabled=True, workflow_id=None
            )
            await session.commit()
        SCHEDULES_TOTAL.set(total)
        ENABLED_SCHEDULES.set(enabled_total)
