"""Tests for CommandGateway: one short-lived transactional operation per call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.application.events.bus import EventBus
from app.core.database import Database
from app.dispatcher.dispatcher import CommandGateway
from app.domains.commands.models import CommandPriority, CommandStatus
from app.domains.commands.repository import CommandRepository
from app.domains.commands.schemas import CommandCreate
from app.domains.commands.service import CommandService
from app.domains.devices.models import Device, DeviceStatus
from app.domains.devices.repository import DeviceRepository


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database for each test."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'dispatcher.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


async def _seed_device(database: Database) -> UUID:
    async with database.session_factory() as session:
        repository = DeviceRepository(session)
        device = Device(
            device_name="agent-1",
            hostname="agent-1.local",
            display_name="Agent One",
            status=DeviceStatus.ONLINE,
            enabled=True,
            metadata_={},
        )
        await repository.create(device)
        await session.commit()
        return device.id


async def _seed_command(database: Database, device_id: UUID, *, max_retries: int = 0) -> UUID:
    async with database.session_factory() as session:
        command_service = CommandService(CommandRepository(session))
        command = await command_service.create_command(
            CommandCreate(
                device_id=device_id,
                command_type="pump.start",
                priority=CommandPriority.NORMAL,
                max_retries=max_retries,
            )
        )
        await session.commit()
        return command.id


@pytest.mark.asyncio
async def test_list_pending_returns_newly_created_commands(database: Database) -> None:
    """A freshly created command is discoverable via list_pending."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id)
    gateway = CommandGateway(database=database, event_bus=EventBus())

    pending = await gateway.list_pending(limit=10)

    assert any(command.id == command_id for command in pending)


@pytest.mark.asyncio
async def test_mark_dispatched_transitions_to_dispatched(database: Database) -> None:
    """mark_dispatched moves a PENDING command to DISPATCHED and publishes an event."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id)
    published = []
    event_bus = EventBus()
    from app.application.events.domain_events import CommandDispatched

    event_bus.subscribe(CommandDispatched, lambda event: published.append(event))
    gateway = CommandGateway(database=database, event_bus=event_bus)

    result = await gateway.mark_dispatched(command_id)

    assert result is not None
    assert result.status is CommandStatus.DISPATCHED
    assert len(published) == 1


@pytest.mark.asyncio
async def test_mark_dispatched_on_an_already_terminal_command_returns_none(
    database: Database,
) -> None:
    """An invalid transition (e.g. already cancelled) is swallowed, not raised."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id)
    gateway = CommandGateway(database=database, event_bus=EventBus())
    await gateway.mark_dispatched(command_id)
    await gateway.mark_running(command_id)
    await gateway.complete_command(command_id, result={})

    # Already COMPLETED; dispatching again is not a legal transition.
    result = await gateway.mark_dispatched(command_id)

    assert result is None


@pytest.mark.asyncio
async def test_full_lifecycle_through_the_gateway(database: Database) -> None:
    """dispatch -> running -> complete moves through the gateway exactly like the app service."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id)
    gateway = CommandGateway(database=database, event_bus=EventBus())

    dispatched = await gateway.mark_dispatched(command_id)
    running = await gateway.mark_running(command_id)
    completed = await gateway.complete_command(command_id, result={"ok": True})

    assert dispatched is not None and dispatched.status is CommandStatus.DISPATCHED
    assert running is not None and running.status is CommandStatus.RUNNING
    assert completed is not None and completed.status is CommandStatus.COMPLETED
    assert completed.result is not None
    assert completed.result.result == {"ok": True}


@pytest.mark.asyncio
async def test_fail_command_records_the_error_message(database: Database) -> None:
    """fail_command records the given error message on the command's result."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id)
    gateway = CommandGateway(database=database, event_bus=EventBus())
    await gateway.mark_dispatched(command_id)

    failed = await gateway.fail_command(command_id, error_message="no ack after 4 retries")

    assert failed is not None
    assert failed.status is CommandStatus.FAILED
    assert failed.result is not None
    assert failed.result.error_message == "no ack after 4 retries"


@pytest.mark.asyncio
async def test_mark_timeout_transitions_a_running_command(database: Database) -> None:
    """mark_timeout transitions a RUNNING command to TIMEOUT."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id)
    gateway = CommandGateway(database=database, event_bus=EventBus())
    await gateway.mark_dispatched(command_id)
    await gateway.mark_running(command_id)

    timed_out = await gateway.mark_timeout(command_id)

    assert timed_out is not None
    assert timed_out.status is CommandStatus.TIMEOUT


@pytest.mark.asyncio
async def test_record_retry_increments_retry_count_without_changing_status(
    database: Database,
) -> None:
    """record_retry bumps retry_count and leaves the command's status untouched."""
    device_id = await _seed_device(database)
    command_id = await _seed_command(database, device_id, max_retries=4)
    gateway = CommandGateway(database=database, event_bus=EventBus())
    await gateway.mark_dispatched(command_id)

    retried = await gateway.record_retry(command_id)

    assert retried is not None
    assert retried.retry_count == 1
    assert retried.status is CommandStatus.DISPATCHED


@pytest.mark.asyncio
async def test_operations_on_an_unknown_command_return_none(database: Database) -> None:
    """Every write operation swallows a CommandNotFound as 'not applicable'."""
    gateway = CommandGateway(database=database, event_bus=EventBus())
    unknown_id = uuid4()

    assert await gateway.mark_dispatched(unknown_id) is None
    assert await gateway.mark_running(unknown_id) is None
    assert await gateway.mark_timeout(unknown_id) is None
    assert await gateway.record_retry(unknown_id) is None
    assert await gateway.complete_command(unknown_id, result={}) is None
    assert await gateway.fail_command(unknown_id, error_message="x") is None
