"""Repository, service, state machine, API, validation, and migration tests for Commands."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Environment, Settings
from app.core.database import Database
from app.domains.commands.exceptions import CommandNotFound, InvalidStateTransition
from app.domains.commands.models import Command, CommandPriority, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import (
    ALLOWED_TRANSITIONS,
    CommandService,
    ensure_transition_allowed,
)
from app.domains.devices.models import Device
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService
from app.main import create_app


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'commands.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """Provide one transaction-scoped session shared by a test's fixtures and body."""
    async with database.session_factory() as session:
        yield session
        try:
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.fixture
async def device(session: AsyncSession) -> Device:
    """Register one enabled device that commands in this test can target."""
    device_service = DeviceService(DeviceRepository(session))
    return await device_service.register_device(
        DeviceCreate.model_validate(
            {
                "device_name": "garden-node",
                "hostname": "garden-node.local",
                "display_name": "Garden node",
            }
        )
    )


@pytest.fixture
def repository(session: AsyncSession) -> CommandRepository:
    """Provide a transaction-scoped repository for persistence-only tests."""
    return CommandRepository(session)


@pytest.fixture
def service(session: AsyncSession) -> CommandService:
    """Provide a transaction-scoped service for lifecycle/business-rule tests."""
    return CommandService(CommandRepository(session))


def command_payload(device_id: UUID, **overrides: object) -> dict[str, object]:
    """Build a valid, generic command request that assumes no particular hardware."""
    payload: dict[str, object] = {
        "device_id": str(device_id),
        "command_type": "pump.start",
        "payload": {"duration_s": 30},
        "priority": "NORMAL",
    }
    payload.update(overrides)
    return payload


# --- Repository --------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_create_and_find(repository: CommandRepository, device: Device) -> None:
    """A created command round-trips through find() with its defaults intact."""
    command = await repository.create(
        Command(device_id=device.id, command_type="pump.start", payload={"duration_s": 5})
    )
    found = await repository.find(command.id)
    assert found is not None
    assert found.status is CommandStatus.PENDING
    assert found.priority is CommandPriority.NORMAL
    assert found.retry_count == 0


@pytest.mark.asyncio
async def test_repository_find_returns_none_for_missing(repository: CommandRepository) -> None:
    """Looking up an unknown command UUID returns None rather than raising."""
    assert (await repository.find(uuid4())) is None


@pytest.mark.asyncio
async def test_repository_find_pending_orders_by_priority_then_age(
    repository: CommandRepository, device: Device
) -> None:
    """Pending commands are returned highest priority first, then oldest first."""
    low = await repository.create(
        Command(device_id=device.id, command_type="pump.start", priority=CommandPriority.LOW)
    )
    critical = await repository.create(
        Command(device_id=device.id, command_type="pump.stop", priority=CommandPriority.CRITICAL)
    )
    high = await repository.create(
        Command(device_id=device.id, command_type="camera.capture", priority=CommandPriority.HIGH)
    )
    pending = await repository.find_pending(device_id=device.id)
    assert [command.id for command in pending] == [critical.id, high.id, low.id]


@pytest.mark.asyncio
async def test_repository_find_pending_excludes_dispatched(
    repository: CommandRepository, device: Device
) -> None:
    """Only PENDING/QUEUED commands are considered awaiting dispatch."""
    command = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    await repository.update_status(command, status=CommandStatus.DISPATCHED)
    assert await repository.find_pending(device_id=device.id) == []


@pytest.mark.asyncio
async def test_repository_find_by_device_paginates(
    repository: CommandRepository, device: Device
) -> None:
    """Pagination bounds the page size while total reflects the full matching count."""
    for _ in range(3):
        await repository.create(Command(device_id=device.id, command_type="pump.start"))
    page, total = await repository.find_by_device(device.id, offset=1, limit=1)
    assert total == 3
    assert len(page) == 1


@pytest.mark.asyncio
async def test_repository_find_all_filters_by_every_supported_field(
    repository: CommandRepository, device: Device
) -> None:
    """Status, device, priority, type, and time-range filters all narrow the result set."""
    matching = await repository.create(
        Command(
            device_id=device.id,
            command_type="pump.start",
            priority=CommandPriority.HIGH,
        )
    )
    await repository.create(Command(device_id=device.id, command_type="camera.capture"))

    commands, total = await repository.find_all(
        status=CommandStatus.PENDING,
        device_id=device.id,
        priority=CommandPriority.HIGH,
        command_type="pump.start",
        created_after=None,
        created_before=None,
        offset=0,
        limit=10,
    )
    assert total == 1
    assert [command.id for command in commands] == [matching.id]

    future_only, future_total = await repository.find_all(
        status=None,
        device_id=None,
        priority=None,
        command_type=None,
        created_after=datetime.now(UTC) + timedelta(days=1),
        created_before=None,
        offset=0,
        limit=10,
    )
    assert future_total == 0
    assert future_only == []

    past_only, past_total = await repository.find_all(
        status=None,
        device_id=None,
        priority=None,
        command_type=None,
        created_after=None,
        created_before=datetime.now(UTC) - timedelta(days=1),
        offset=0,
        limit=10,
    )
    assert past_total == 0
    assert past_only == []


@pytest.mark.asyncio
async def test_repository_find_all_sorts_by_priority_rank_not_alphabetically(
    repository: CommandRepository, device: Device
) -> None:
    """Priority sort must use dispatch-rank order, never the raw string order."""
    low = await repository.create(
        Command(device_id=device.id, command_type="pump.start", priority=CommandPriority.LOW)
    )
    critical = await repository.create(
        Command(device_id=device.id, command_type="pump.stop", priority=CommandPriority.CRITICAL)
    )
    commands, _ = await repository.find_all(
        status=None,
        device_id=None,
        priority=None,
        command_type=None,
        created_after=None,
        created_before=None,
        offset=0,
        limit=10,
        sort="-priority",
    )
    assert [command.id for command in commands] == [critical.id, low.id]


@pytest.mark.asyncio
async def test_repository_find_all_falls_back_to_created_at_for_an_unknown_sort_key(
    repository: CommandRepository, device: Device
) -> None:
    """An unvalidated sort token (bypassing the API's regex) still yields a stable order."""
    # Explicit, distinct timestamps: SQLite's CURRENT_TIMESTAMP default only has
    # whole-second resolution, so two commands created back-to-back would
    # otherwise tie on created_at and make this assertion depend on however
    # the repository's secondary tiebreaker happens to order them.
    now = datetime.now(UTC)
    older = await repository.create(
        Command(
            device_id=device.id, command_type="pump.start", created_at=now - timedelta(seconds=5)
        )
    )
    newer = await repository.create(
        Command(device_id=device.id, command_type="pump.stop", created_at=now)
    )
    commands, _ = await repository.find_all(
        status=None,
        device_id=None,
        priority=None,
        command_type=None,
        created_after=None,
        created_before=None,
        offset=0,
        limit=10,
        sort="not-a-real-field",
    )
    assert [command.id for command in commands] == [newer.id, older.id]


@pytest.mark.asyncio
async def test_repository_find_expirable_excludes_terminal_and_future(
    repository: CommandRepository, device: Device
) -> None:
    """Only non-terminal commands whose expiry has already passed are expirable."""
    now = datetime.now(UTC)
    expired_pending = await repository.create(
        Command(
            device_id=device.id, command_type="pump.start", expires_at=now - timedelta(minutes=1)
        )
    )
    await repository.create(
        Command(device_id=device.id, command_type="pump.stop", expires_at=now + timedelta(hours=1))
    )
    already_cancelled = await repository.create(
        Command(
            device_id=device.id,
            command_type="camera.capture",
            expires_at=now - timedelta(minutes=1),
        )
    )
    await repository.cancel(already_cancelled, cancelled_at=now)

    expirable = await repository.find_expirable(now)
    assert [command.id for command in expirable] == [expired_pending.id]


@pytest.mark.asyncio
async def test_repository_find_interrupted_only_dispatched_and_running(
    repository: CommandRepository, device: Device
) -> None:
    """Only DISPATCHED/RUNNING commands are interrupted; other statuses are not."""
    dispatched = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    await repository.update_status(dispatched, status=CommandStatus.DISPATCHED)
    running = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    await repository.update_status(running, status=CommandStatus.RUNNING)
    pending = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    completed = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    await repository.update_status(completed, status=CommandStatus.COMPLETED)

    interrupted = await repository.find_interrupted()
    interrupted_ids = {command.id for command in interrupted}
    assert interrupted_ids == {dispatched.id, running.id}
    assert pending.id not in interrupted_ids
    assert completed.id not in interrupted_ids


@pytest.mark.asyncio
async def test_repository_update_status_sets_started_and_completed(
    repository: CommandRepository, device: Device
) -> None:
    """update_status applies only the timestamp fields explicitly provided."""
    command = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    started_at = datetime.now(UTC)
    updated = await repository.update_status(
        command, status=CommandStatus.RUNNING, started_at=started_at
    )
    assert updated.status is CommandStatus.RUNNING
    assert updated.started_at == started_at
    assert updated.completed_at is None


@pytest.mark.asyncio
async def test_repository_store_result_is_one_to_one(
    repository: CommandRepository, device: Device
) -> None:
    """A command's result is reachable from the command after being stored."""
    command = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    await repository.store_result(
        command,
        success=True,
        exit_code=0,
        result={"ok": True},
        error_message=None,
        duration_ms=42,
    )
    assert command.result is not None
    assert command.result.success is True
    assert command.result.duration_ms == 42


@pytest.mark.asyncio
async def test_repository_append_event_orders_by_timestamp(
    repository: CommandRepository, device: Device
) -> None:
    """Appended events remain visible on the command in chronological order."""
    command = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    from app.domains.commands.events import CommandEventType

    await repository.append_event(command, event_type=CommandEventType.COMMAND_CREATED)
    await repository.append_event(command, event_type=CommandEventType.COMMAND_DISPATCHED)
    assert [event.event_type for event in command.events] == [
        CommandEventType.COMMAND_CREATED,
        CommandEventType.COMMAND_DISPATCHED,
    ]


@pytest.mark.asyncio
async def test_repository_cancel_and_expire_set_status_and_completed_at(
    repository: CommandRepository, device: Device
) -> None:
    """cancel() and expire() both stamp completed_at alongside the terminal status."""
    cancelled = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    now = datetime.now(UTC)
    await repository.cancel(cancelled, cancelled_at=now)
    assert cancelled.status is CommandStatus.CANCELLED
    assert cancelled.completed_at == now

    expired = await repository.create(Command(device_id=device.id, command_type="pump.stop"))
    await repository.expire(expired, status=CommandStatus.EXPIRED, expired_at=now)
    assert expired.status is CommandStatus.EXPIRED
    assert expired.completed_at == now


@pytest.mark.asyncio
async def test_repository_soft_delete_excludes_the_command_from_find_and_find_all(
    repository: CommandRepository, device: Device
) -> None:
    """A soft-deleted command disappears from find() and find_all() alike, never hard-deleted."""
    command = await repository.create(Command(device_id=device.id, command_type="pump.start"))
    await repository.soft_delete(command, at=datetime.now(UTC))

    assert (await repository.find(command.id)) is None
    commands, total = await repository.find_all(
        status=None,
        device_id=None,
        priority=None,
        command_type=None,
        created_after=None,
        created_before=None,
        offset=0,
        limit=10,
    )
    assert command.id not in [c.id for c in commands]
    assert total == 0
    assert command.deleted_at is not None


# --- State machine -------------------------------------------------------------


@pytest.mark.parametrize("current", list(CommandStatus))
def test_state_machine_matches_the_allowed_transition_table_exactly(
    current: CommandStatus,
) -> None:
    """Every (current, target) pair either matches the table or raises, with no gaps."""
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    for target in CommandStatus:
        if target in allowed:
            ensure_transition_allowed(current, target)
        else:
            with pytest.raises(InvalidStateTransition):
                ensure_transition_allowed(current, target)


def test_state_machine_terminal_statuses_allow_no_transitions() -> None:
    """Completed, failed, cancelled, expired, and timed-out commands cannot restart."""
    terminal = (
        CommandStatus.COMPLETED,
        CommandStatus.FAILED,
        CommandStatus.CANCELLED,
        CommandStatus.EXPIRED,
        CommandStatus.TIMEOUT,
    )
    for status in terminal:
        assert ALLOWED_TRANSITIONS.get(status, frozenset()) == frozenset()


# --- Service -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_create_command_does_not_validate_device_existence(
    service: CommandService,
) -> None:
    """The domain never cross-checks devices; that is an application-layer concern.

    Confirming the target device exists and is enabled now lives in
    ``CommandApplicationService`` (see ``test_application_services.py``).
    """
    command = await service.create_command(CommandCreate.model_validate(command_payload(uuid4())))
    assert command.status is CommandStatus.PENDING


@pytest.mark.asyncio
async def test_service_create_command_emits_a_created_event(
    service: CommandService, device: Device
) -> None:
    """Registering a command is itself a lifecycle transition with its own event."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    assert command.status is CommandStatus.PENDING
    assert [event.event_type.value for event in command.events] == ["COMMAND_CREATED"]
    assert command.correlation_id is not None


@pytest.mark.asyncio
async def test_service_full_lifecycle_to_completion(
    service: CommandService, device: Device
) -> None:
    """A command can be walked from creation through to a successful result."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    await service.mark_dispatched(command.id)
    await service.mark_running(command.id)
    completed = await service.complete_command(
        command.id, result={"ok": True}, exit_code=0, duration_ms=100
    )
    assert completed.status is CommandStatus.COMPLETED
    assert completed.result is not None
    assert completed.result.success is True
    assert [event.event_type.value for event in completed.events] == [
        "COMMAND_CREATED",
        "COMMAND_DISPATCHED",
        "COMMAND_STARTED",
        "COMMAND_COMPLETED",
    ]


@pytest.mark.asyncio
async def test_service_full_lifecycle_to_failure(service: CommandService, device: Device) -> None:
    """A command can be walked from creation through to a failed result."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    await service.mark_dispatched(command.id)
    await service.mark_running(command.id)
    failed = await service.fail_command(command.id, error_message="pump stalled", exit_code=1)
    assert failed.status is CommandStatus.FAILED
    assert failed.result is not None
    assert failed.result.success is False
    assert failed.result.error_message == "pump stalled"


@pytest.mark.asyncio
async def test_service_cancel_allowed_before_and_during_execution(
    service: CommandService, device: Device
) -> None:
    """Cancellation is valid from PENDING and from RUNNING, each with its own reason."""
    pending = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    cancelled = await service.cancel_command(pending.id, reason="operator abort")
    assert cancelled.status is CommandStatus.CANCELLED
    assert cancelled.events[-1].details == {"reason": "operator abort"}

    running = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    await service.mark_dispatched(running.id)
    await service.mark_running(running.id)
    cancelled_running = await service.cancel_command(running.id)
    assert cancelled_running.status is CommandStatus.CANCELLED


@pytest.mark.asyncio
async def test_service_cancel_after_terminal_raises_invalid_transition(
    service: CommandService, device: Device
) -> None:
    """A command cannot be cancelled once it has already reached a terminal state."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    await service.mark_dispatched(command.id)
    await service.mark_running(command.id)
    await service.complete_command(command.id, result={})
    with pytest.raises(InvalidStateTransition):
        await service.cancel_command(command.id)


@pytest.mark.asyncio
async def test_service_delete_command_requires_a_terminal_state(
    service: CommandService, device: Device
) -> None:
    """A still-in-flight command cannot be deleted — cancel it first."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    with pytest.raises(InvalidStateTransition):
        await service.delete_command(command.id)


@pytest.mark.asyncio
async def test_service_delete_command_removes_a_terminal_command_from_history(
    service: CommandService, device: Device
) -> None:
    """A terminal command can be deleted, and then behaves as though it never existed."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    await service.mark_dispatched(command.id)
    await service.mark_running(command.id)
    await service.complete_command(command.id, result={})

    await service.delete_command(command.id)

    with pytest.raises(CommandNotFound):
        await service.get_command(command.id)


@pytest.mark.asyncio
async def test_service_delete_command_raises_for_an_unknown_id(service: CommandService) -> None:
    with pytest.raises(CommandNotFound):
        await service.delete_command(uuid4())


@pytest.mark.asyncio
async def test_service_mark_running_requires_dispatched_first(
    service: CommandService, device: Device
) -> None:
    """Skipping DISPATCHED and going straight to RUNNING is an invalid transition."""
    command = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    with pytest.raises(InvalidStateTransition):
        await service.mark_running(command.id)


@pytest.mark.asyncio
async def test_service_get_command_raises_not_found(service: CommandService) -> None:
    """Looking up an unknown command UUID raises the domain not-found error."""
    with pytest.raises(CommandNotFound):
        await service.get_command(uuid4())


@pytest.mark.asyncio
async def test_service_expire_old_commands_marks_pending_expired_and_running_timeout(
    service: CommandService, device: Device
) -> None:
    """A single sweep resolves both queue-wait expiry and execution timeout."""
    soon = datetime.now(UTC) + timedelta(seconds=5)
    pending = await service.create_command(
        CommandCreate.model_validate(command_payload(device.id, expires_at=soon.isoformat()))
    )
    running = await service.create_command(
        CommandCreate.model_validate(command_payload(device.id, expires_at=soon.isoformat()))
    )
    await service.mark_dispatched(running.id)
    await service.mark_running(running.id)

    as_of = soon + timedelta(seconds=1)
    expired_count = await service.expire_old_commands(now=as_of)
    assert expired_count == 2

    expired_pending = await service.get_command(pending.id)
    expired_running = await service.get_command(running.id)
    assert expired_pending.status is CommandStatus.EXPIRED
    assert expired_running.status is CommandStatus.TIMEOUT
    assert expired_pending.events[-1].event_type.value == "COMMAND_EXPIRED"
    assert expired_running.events[-1].event_type.value == "COMMAND_TIMEOUT"


@pytest.mark.asyncio
async def test_service_reconcile_interrupted_commands_fails_dispatched_and_running(
    service: CommandService, device: Device
) -> None:
    """A restart-orphaned DISPATCHED/RUNNING command is failed, not left stuck forever."""
    dispatched = await service.create_command(
        CommandCreate.model_validate(command_payload(device.id))
    )
    await service.mark_dispatched(dispatched.id)

    running = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))
    await service.mark_dispatched(running.id)
    await service.mark_running(running.id)

    pending = await service.create_command(CommandCreate.model_validate(command_payload(device.id)))

    reconciled_count = await service.reconcile_interrupted_commands()
    assert reconciled_count == 2

    reconciled_dispatched = await service.get_command(dispatched.id)
    reconciled_running = await service.get_command(running.id)
    still_pending = await service.get_command(pending.id)
    assert reconciled_dispatched.status is CommandStatus.FAILED
    assert reconciled_dispatched.result is not None
    assert reconciled_dispatched.result.error_message == "interrupted by server restart"
    assert reconciled_running.status is CommandStatus.FAILED
    assert still_pending.status is CommandStatus.PENDING

    # The now-terminal commands can be deleted from History; the still-in-flight one cannot.
    await service.delete_command(dispatched.id)


# --- Validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "invalid_type", ["PumpStart", "pump", "Pump.Start", "pump.", ".start", "pump start", ""]
)
def test_validation_rejects_malformed_command_types(invalid_type: str) -> None:
    """command_type must be a lowercase, dot-namespaced identifier."""
    with pytest.raises(ValidationError):
        CommandCreate.model_validate(command_payload(uuid4(), command_type=invalid_type))


@pytest.mark.parametrize(
    "valid_type",
    ["pump.start", "camera.capture", "filesystem.upload", "system.reboot", "sensor.read"],
)
def test_validation_accepts_generic_namespaced_command_types(valid_type: str) -> None:
    """The domain never hardcodes hardware-specific command types."""
    command = CommandCreate.model_validate(command_payload(uuid4(), command_type=valid_type))
    assert command.command_type == valid_type


def test_validation_rejects_expiration_before_scheduled_time() -> None:
    """expires_at must leave a real window after scheduled_at to execute."""
    scheduled = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(ValidationError, match="expires_at"):
        CommandCreate.model_validate(
            command_payload(
                uuid4(),
                scheduled_at=scheduled.isoformat(),
                expires_at=scheduled.isoformat(),
            )
        )


def test_validation_rejects_expiration_already_in_the_past() -> None:
    """An expires_at with no scheduled_at must still lie in the future."""
    past = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(ValidationError, match="future"):
        CommandCreate.model_validate(command_payload(uuid4(), expires_at=past.isoformat()))


def test_validation_accepts_a_consistent_scheduling_window() -> None:
    """A well-formed scheduled_at/expires_at pair is accepted."""
    scheduled = datetime.now(UTC) + timedelta(hours=1)
    expires = scheduled + timedelta(hours=1)
    command = CommandCreate.model_validate(
        command_payload(uuid4(), scheduled_at=scheduled.isoformat(), expires_at=expires.isoformat())
    )
    assert command.expires_at == expires


def test_validation_bounds_max_retries() -> None:
    """max_retries is bounded to a small, sane range."""
    with pytest.raises(ValidationError):
        CommandCreate.model_validate(command_payload(uuid4(), max_retries=11))
    with pytest.raises(ValidationError):
        CommandCreate.model_validate(command_payload(uuid4(), max_retries=-1))


# --- API -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_command_lifecycle_and_domain_error_mapping(database: Database) -> None:
    """The API creates, lists, fetches, and cancels commands with RFC 7807 errors."""
    async with database.session_factory() as setup_session:
        device = await DeviceService(DeviceRepository(setup_session)).register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "garden-node",
                    "hostname": "garden-node.local",
                    "display_name": "Garden node",
                }
            )
        )
        await setup_session.commit()
        device_id = device.id

    app: FastAPI = create_app(
        Settings(ENVIRONMENT=Environment.TEST, DATABASE_URL="sqlite+aiosqlite:///:memory:")
    )
    app.state.container.database.override(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing_device = await client.post("/commands", json=command_payload(uuid4()))
        assert missing_device.status_code == 404
        assert missing_device.headers["content-type"].startswith("application/problem+json")

        invalid = await client.post(
            "/commands", json=command_payload(device_id, command_type="not-namespaced")
        )
        assert invalid.status_code == 422

        created = await client.post("/commands", json=command_payload(device_id))
        assert created.status_code == 201
        body = created.json()
        command_id = body["id"]
        assert body["status"] == "PENDING"
        assert body["events"][0]["event_type"] == "COMMAND_CREATED"
        assert body["result"] is None

        fetched = await client.get(f"/commands/{command_id}")
        assert fetched.status_code == 200
        assert fetched.json()["command_type"] == "pump.start"

        missing = await client.get(f"/commands/{uuid4()}")
        assert missing.status_code == 404

        listed = await client.get(
            "/commands", params={"device": str(device_id), "status": "PENDING", "limit": 10}
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        cancelled = await client.post(
            f"/commands/{command_id}/cancel", json={"reason": "operator abort"}
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"

        already_terminal = await client.post(f"/commands/{command_id}/cancel")
        assert already_terminal.status_code == 409
        assert already_terminal.headers["content-type"].startswith("application/problem+json")

        cancel_missing = await client.post(f"/commands/{uuid4()}/cancel")
        assert cancel_missing.status_code == 404

        # `cancelled` above is already terminal (CANCELLED), so it can be deleted.
        deleted = await client.delete(f"/commands/{command_id}")
        assert deleted.status_code == 204
        assert (await client.get(f"/commands/{command_id}")).status_code == 404

        delete_missing = await client.delete(f"/commands/{uuid4()}")
        assert delete_missing.status_code == 404

        non_terminal = await client.post("/commands", json=command_payload(device_id))
        non_terminal_id = non_terminal.json()["id"]
        delete_non_terminal = await client.delete(f"/commands/{non_terminal_id}")
        assert delete_non_terminal.status_code == 409
        assert delete_non_terminal.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_api_rejects_commands_for_a_disabled_device(database: Database) -> None:
    """A disabled device yields a safe 409 rather than silently accepting commands."""
    async with database.session_factory() as setup_session:
        device_service = DeviceService(DeviceRepository(setup_session))
        device = await device_service.register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "garden-node",
                    "hostname": "garden-node.local",
                    "display_name": "Garden node",
                }
            )
        )
        await device_service.disable(device.id)
        await setup_session.commit()
        device_id = device.id

    app: FastAPI = create_app(
        Settings(ENVIRONMENT=Environment.TEST, DATABASE_URL="sqlite+aiosqlite:///:memory:")
    )
    app.state.container.database.override(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/commands", json=command_payload(device_id))
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_api_list_commands_supports_sort_and_rejects_bad_sort_values(
    database: Database,
) -> None:
    """The sort query parameter is validated and drives real ordering."""
    async with database.session_factory() as setup_session:
        device = await DeviceService(DeviceRepository(setup_session)).register_device(
            DeviceCreate.model_validate(
                {
                    "device_name": "garden-node",
                    "hostname": "garden-node.local",
                    "display_name": "Garden node",
                }
            )
        )
        await setup_session.commit()
        device_id = device.id

    app: FastAPI = create_app(
        Settings(ENVIRONMENT=Environment.TEST, DATABASE_URL="sqlite+aiosqlite:///:memory:")
    )
    app.state.container.database.override(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/commands", json=command_payload(device_id, priority="LOW"))
        await client.post(
            "/commands",
            json=command_payload(device_id, command_type="pump.stop", priority="CRITICAL"),
        )

        bad_sort = await client.get("/commands", params={"sort": "not-a-field"})
        assert bad_sort.status_code == 422

        sorted_by_priority = await client.get("/commands", params={"sort": "-priority"})
        assert sorted_by_priority.status_code == 200
        priorities = [item["priority"] for item in sorted_by_priority.json()["items"]]
        assert priorities == ["CRITICAL", "LOW"]


@pytest.mark.asyncio
async def test_api_returns_503_without_configured_database() -> None:
    """The Command domain endpoints fail safely when no database is configured."""
    app: FastAPI = create_app(Settings(ENVIRONMENT=Environment.TEST))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/commands")
    assert response.status_code == 503


# --- Migration ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_metadata_contains_required_tables(database: Database) -> None:
    """The model metadata used by the migration exposes all three command tables."""
    async with database._engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert {"commands", "command_results", "command_events"}.issubset(table_names)
