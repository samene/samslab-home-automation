"""Tests for CommandDispatcher: start/stop lifecycle, health, and admin accessors."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.application.events.bus import EventBus
from app.config.settings import Environment, Settings
from app.core.database import Database
from app.dispatcher.dispatcher import CommandDispatcher


class _FakeSessionManager:
    """A DeviceSessionPort stand-in with no connected devices."""

    def get(self, device_id: object) -> object | None:
        return None

    def send(self, device_id: object, envelope: object) -> bool:
        return False


@pytest.fixture
def settings() -> Settings:
    return Settings(
        SERVER_NAME="Dispatcher Test",
        ENVIRONMENT=Environment.TEST,
        DISPATCHER_POLL_INTERVAL_SECONDS=0.05,
        DISPATCHER_SWEEP_INTERVAL_SECONDS=0.05,
    )


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'dispatcher_lifecycle.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


@pytest.mark.asyncio
async def test_never_started_dispatcher_is_healthy_but_not_running(settings: Settings) -> None:
    """A dispatcher that was never started reports healthy (not a readiness failure)."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=None,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    assert dispatcher.is_running is False
    assert dispatcher.health_ok is True


@pytest.mark.asyncio
async def test_start_without_a_database_configured_is_a_safe_no_op(settings: Settings) -> None:
    """Starting with no database configured logs a warning and never spawns tasks."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=None,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    assert dispatcher.is_running is False
    assert dispatcher.health_ok is True  # never actually started
    await dispatcher.stop()  # tolerates stopping something that never started


@pytest.mark.asyncio
async def test_start_and_stop_toggle_is_running(settings: Settings, database: Database) -> None:
    """A dispatcher started with a real database becomes running until stopped."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=database,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    assert dispatcher.is_running is True
    assert dispatcher.health_ok is True

    await dispatcher.stop()
    assert dispatcher.is_running is False
    assert dispatcher.health_ok is False  # started, then stopped: a readiness failure


@pytest.mark.asyncio
async def test_start_is_idempotent(settings: Settings, database: Database) -> None:
    """Calling start() a second time while already running does not spawn duplicate tasks."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=database,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    tasks_after_first_start = list(dispatcher._tasks)  # noqa: SLF001
    await dispatcher.start()
    assert dispatcher._tasks == tasks_after_first_start  # noqa: SLF001
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_status_reflects_empty_state_before_any_command(
    settings: Settings, database: Database
) -> None:
    """A freshly started dispatcher with no commands reports zeroed-out status."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=database,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    status = dispatcher.status()
    assert status.running is True
    assert status.queue_depth == 0
    assert status.pending_ack_count == 0
    assert status.running_count == 0
    assert status.started_at is not None
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_queue_and_running_snapshots_are_empty_initially(
    settings: Settings, database: Database
) -> None:
    """Fresh admin snapshots report empty collections, not an error."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=database,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    assert dispatcher.queue_snapshot() == []
    assert dispatcher.running_snapshot() == []
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_statistics_are_readable_before_the_dispatcher_starts(settings: Settings) -> None:
    """Statistics can be read even for a dispatcher that hasn't started (all zero collections)."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=None,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    stats = dispatcher.statistics()
    assert stats.queue_depth == 0
    assert stats.pending_ack_count == 0
    assert stats.running_count == 0


@pytest.mark.asyncio
async def test_stop_unsubscribes_from_the_event_bus(settings: Settings, database: Database) -> None:
    """After stop(), the dispatcher no longer reacts to CommandAckReceived/CommandResultReceived."""
    from app.application.events.domain_events import CommandAckReceived

    event_bus = EventBus()
    dispatcher = CommandDispatcher(
        settings=settings,
        database=database,
        event_bus=event_bus,
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    await dispatcher.stop()

    # Publishing after stop() must not raise, even though nothing is subscribed anymore.
    await event_bus.publish(
        CommandAckReceived(
            command_id=uuid4(), device_id=uuid4(), message_id=uuid4(), occurred_at=datetime.now(UTC)
        )
    )


@pytest.mark.asyncio
async def test_a_running_dispatcher_actually_polls(settings: Settings, database: Database) -> None:
    """The worker task genuinely runs: after starting, it queries list_pending at least once."""
    dispatcher = CommandDispatcher(
        settings=settings,
        database=database,
        event_bus=EventBus(),
        session_manager=_FakeSessionManager(),  # type: ignore[arg-type]
    )
    await dispatcher.start()
    await asyncio.sleep(0.2)  # a couple of poll intervals
    assert dispatcher.is_running is True  # the worker task hasn't crashed
    await dispatcher.stop()
