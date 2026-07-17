"""The Command Dispatcher: a background service wiring together the whole delivery pipeline.

This is the composition root for the ``app/dispatcher/`` package — the one
place that constructs and wires ``DeliveryService``, ``AckManager``,
``TimeoutMonitor``, ``ResultHandler``, and ``DispatchWorker``, subscribes them
to the shared event bus, and exposes ``start``/``stop``/read-only status
accessors for the FastAPI lifespan and the admin REST endpoints.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from app.application.dto.command_dto import CommandDetailDTO
from app.application.dto.dispatcher_dto import (
    DispatcherQueueItemDTO,
    DispatcherRunningItemDTO,
    DispatcherStatisticsDTO,
    DispatcherStatusDTO,
)
from app.application.events.bus import EventBus
from app.application.events.domain_events import CommandAckReceived, CommandResultReceived
from app.application.exceptions import ApplicationError
from app.application.services.command_service import CommandApplicationService
from app.config.settings import Settings
from app.core.database import Database
from app.dispatcher.ack_manager import AckManager
from app.dispatcher.config import DispatcherConfig
from app.dispatcher.delivery import DeliveryService
from app.dispatcher.interfaces import DeviceSessionPort
from app.dispatcher.metrics import (
    COMMANDS_DISPATCHED_TOTAL,
    DISPATCH_FAILURES_TOTAL,
    DISPATCHER_RETRIES_TOTAL,
    DISPATCHER_TIMEOUTS_TOTAL,
    read_counter,
)
from app.dispatcher.queue import DispatchQueue
from app.dispatcher.result_handler import ResultHandler
from app.dispatcher.timeouts import TimeoutMonitor
from app.dispatcher.worker import DispatchWorker
from app.domains.commands.repository import CommandRepository
from app.domains.commands.service import CommandService
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.service import DeviceService

logger: Any = structlog.get_logger("dispatcher")


class CommandGateway:
    """Open one short-lived, transactional ``CommandApplicationService`` per operation.

    The dispatcher runs as a long-lived background service, not a per-request
    handler, so — exactly like ``WebSocketGateway`` does for ``DeviceApplicationService``
    — every write opens its own session, commits on success, and rolls back
    on failure. A domain failure that means "not applicable anymore" (e.g. a
    command cancelled out from under a dispatch attempt) is swallowed and
    logged rather than propagated, since the caller has no compensating
    action beyond skipping this command for now.
    """

    def __init__(self, *, database: Database, event_bus: EventBus) -> None:
        """Bind to the shared database and event bus used to build each service."""
        self._database = database
        self._event_bus = event_bus

    async def list_pending(self, *, limit: int) -> list[CommandDetailDTO]:
        """Return commands awaiting dispatch, highest priority and oldest first."""
        async with self._database.session_factory() as session:
            service = self._build_service(session)
            commands = await service.list_pending_commands(limit=limit)
            await session.commit()
            return commands

    async def mark_dispatched(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record that a command has been handed to a transport for delivery."""
        return await self._run(command_id, lambda service: service.mark_dispatched(command_id))

    async def mark_running(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record that execution has started on the target device."""
        return await self._run(command_id, lambda service: service.mark_running(command_id))

    async def mark_timeout(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record that a command never produced a result in time."""
        return await self._run(command_id, lambda service: service.mark_timeout(command_id))

    async def record_retry(self, command_id: UUID) -> CommandDetailDTO | None:
        """Record one more redelivery attempt against a command."""
        return await self._run(command_id, lambda service: service.record_retry(command_id))

    async def complete_command(
        self, command_id: UUID, *, result: dict[str, Any]
    ) -> CommandDetailDTO | None:
        """Record a successful terminal outcome."""
        return await self._run(
            command_id, lambda service: service.complete_command(command_id, result=result)
        )

    async def fail_command(
        self, command_id: UUID, *, error_message: str
    ) -> CommandDetailDTO | None:
        """Record a failed terminal outcome."""
        return await self._run(
            command_id,
            lambda service: service.fail_command(command_id, error_message=error_message),
        )

    def _build_service(self, session: Any) -> CommandApplicationService:
        return CommandApplicationService(
            CommandService(CommandRepository(session)),
            DeviceService(DeviceRepository(session)),
            self._event_bus,
        )

    async def _run(self, command_id: UUID, operation: Any) -> CommandDetailDTO | None:
        async with self._database.session_factory() as session:
            service = self._build_service(session)
            try:
                result = await operation(service)
                await session.commit()
                return result  # type: ignore[no-any-return]
            except ApplicationError as error:
                await session.rollback()
                logger.info(
                    "dispatcher_command_operation_skipped",
                    command_id=str(command_id),
                    reason=str(error),
                )
                return None


class CommandDispatcher:
    """Discover, deliver, acknowledge, time out, retry, and complete commands — nothing else."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database | None,
        event_bus: EventBus,
        session_manager: DeviceSessionPort,
    ) -> None:
        """Bind to the shared, per-application infrastructure this dispatcher will use."""
        self._settings = settings
        self._database = database
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._config = DispatcherConfig.from_settings(settings)
        self._queue = DispatchQueue()
        self._gateway: CommandGateway | None = None
        self._delivery: DeliveryService | None = None
        self._ack_manager: AckManager | None = None
        self._timeout_monitor: TimeoutMonitor | None = None
        self._result_handler: ResultHandler | None = None
        self._worker: DispatchWorker | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._started_at: datetime | None = None
        self._ever_started = False

    @property
    def is_running(self) -> bool:
        """Whether the background tasks are currently alive."""
        return bool(self._tasks) and all(not task.done() for task in self._tasks)

    @property
    def health_ok(self) -> bool:
        """Whether ``/ready`` should consider the dispatcher healthy.

        A dispatcher that was never started (e.g. no database configured) is
        not a readiness failure — only one that started and then stopped
        (its worker task died) is.
        """
        if not self._ever_started:
            return True
        return self.is_running

    async def start(self) -> None:
        """Wire the delivery pipeline and start its background tasks; a no-op if already running."""
        if self._database is None:
            logger.warning("dispatcher_not_started_no_database")
            return
        if self._tasks:
            return
        self._gateway = CommandGateway(database=self._database, event_bus=self._event_bus)
        self._delivery = DeliveryService(session_manager=self._session_manager)
        self._timeout_monitor = TimeoutMonitor(gateway=self._gateway, config=self._config)
        self._ack_manager = AckManager(
            gateway=self._gateway,
            delivery=self._delivery,
            config=self._config,
            on_running=self._timeout_monitor.track,
            event_bus=self._event_bus,
        )
        self._result_handler = ResultHandler(
            gateway=self._gateway, timeout_monitor=self._timeout_monitor
        )
        self._worker = DispatchWorker(
            queue=self._queue,
            gateway=self._gateway,
            delivery=self._delivery,
            ack_manager=self._ack_manager,
            config=self._config,
            event_bus=self._event_bus,
        )
        self._event_bus.subscribe(CommandAckReceived, self._ack_manager.handle_ack)
        self._event_bus.subscribe(CommandResultReceived, self._result_handler.handle_result)
        self._tasks = [
            asyncio.create_task(self._worker.run()),
            asyncio.create_task(self._ack_manager.run()),
            asyncio.create_task(self._timeout_monitor.run()),
        ]
        self._started_at = datetime.now(UTC)
        self._ever_started = True
        logger.info("dispatcher_started")

    async def stop(self) -> None:
        """Unsubscribe from the event bus and cancel every background task."""
        if self._ack_manager is not None:
            self._event_bus.unsubscribe(CommandAckReceived, self._ack_manager.handle_ack)
        if self._result_handler is not None:
            self._event_bus.unsubscribe(CommandResultReceived, self._result_handler.handle_result)
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        logger.info("dispatcher_stopped")

    def status(self) -> DispatcherStatusDTO:
        """A snapshot of the dispatcher's own run state, for ``GET /dispatcher/status``."""
        return DispatcherStatusDTO(
            running=self.is_running,
            started_at=self._started_at,
            queue_depth=len(self._queue),
            pending_ack_count=len(self._ack_manager.snapshot()) if self._ack_manager else 0,
            running_count=len(self._timeout_monitor.snapshot()) if self._timeout_monitor else 0,
            poll_interval_seconds=self._config.poll_interval_seconds,
        )

    def queue_snapshot(self) -> list[DispatcherQueueItemDTO]:
        """Every command currently waiting in the in-memory queue, for ``GET /dispatcher/queue``."""
        return [
            DispatcherQueueItemDTO(
                command_id=item.command_id,
                device_id=item.device_id,
                priority=item.priority,
                command_type=item.command_type,
                enqueued_at=item.enqueued_at,
            )
            for item in self._queue.snapshot()
        ]

    def running_snapshot(self) -> list[DispatcherRunningItemDTO]:
        """Every command past dispatch, for ``GET /dispatcher/running``."""
        items: list[DispatcherRunningItemDTO] = []
        if self._ack_manager is not None:
            items.extend(
                DispatcherRunningItemDTO(
                    command_id=item.command_id,
                    device_id=item.device_id,
                    command_type=item.command_type,
                    phase="awaiting_ack",
                )
                for item in self._ack_manager.snapshot()
            )
        if self._timeout_monitor is not None:
            items.extend(
                DispatcherRunningItemDTO(
                    command_id=item.command_id,
                    device_id=item.device_id,
                    command_type=item.command_type,
                    phase="running",
                )
                for item in self._timeout_monitor.snapshot()
            )
        return items

    def statistics(self) -> DispatcherStatisticsDTO:
        """The dispatcher's own operational counters, for ``GET /dispatcher/statistics``."""
        return DispatcherStatisticsDTO(
            commands_dispatched_total=int(read_counter(COMMANDS_DISPATCHED_TOTAL)),
            dispatch_failures_total=int(read_counter(DISPATCH_FAILURES_TOTAL)),
            dispatcher_retries_total=int(read_counter(DISPATCHER_RETRIES_TOTAL)),
            dispatcher_timeouts_total=int(read_counter(DISPATCHER_TIMEOUTS_TOTAL)),
            queue_depth=len(self._queue),
            pending_ack_count=len(self._ack_manager.snapshot()) if self._ack_manager else 0,
            running_count=len(self._timeout_monitor.snapshot()) if self._timeout_monitor else 0,
        )
