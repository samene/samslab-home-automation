"""Repository and service tests for the Snapshots domain, mirroring test_devices.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.domains.commands.models import Command
from app.domains.commands.repository import CommandRepository
from app.domains.devices.models import Device
from app.domains.devices.repository import DeviceRepository
from app.domains.devices.schemas import DeviceCreate
from app.domains.devices.service import DeviceService
from app.domains.snapshots.exceptions import SnapshotNotFound
from app.domains.snapshots.models import Snapshot
from app.domains.snapshots.repository import SnapshotRepository
from app.domains.snapshots.service import SnapshotService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh file-backed SQLite database registering every domain's tables."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'snapshots.db'}")
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
    """Register one enabled device that snapshots in this test can target."""
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


async def _make_command(session: AsyncSession, device_id: UUID) -> Command:
    """Create a real command row so a snapshot's unique command_id FK has something to target."""
    return await CommandRepository(session).create(
        Command(device_id=device_id, command_type="camera.snapshot", payload={})
    )


@pytest.fixture
def repository(session: AsyncSession) -> SnapshotRepository:
    """Provide a transaction-scoped repository for persistence-only tests."""
    return SnapshotRepository(session)


@pytest.fixture
def service(session: AsyncSession) -> SnapshotService:
    """Provide a transaction-scoped service for repository/service tests."""
    return SnapshotService(SnapshotRepository(session))


def snapshot_kwargs(
    *, device_id: UUID, command_id: UUID, captured_at: datetime | None = None, **overrides: Any
) -> dict[str, Any]:
    """Build a valid record_snapshot()/Snapshot(...) kwargs set."""
    values: dict[str, Any] = {
        "device_id": device_id,
        "command_id": command_id,
        "filename": "snapshot.jpg",
        "bucket": "samslab-snapshots",
        "original_object_key": "originals/snapshot.jpg",
        "thumbnail_object_key": "thumbnails/snapshot.jpg",
        "etag": "\"abc123\"",
        "sha256": "a" * 64,
        "width": 1920,
        "height": 1080,
        "size": 204800,
        "captured_at": captured_at or datetime.now(UTC),
    }
    values.update(overrides)
    return values


# --- Repository -------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_create_and_find_by_id(
    repository: SnapshotRepository, session: AsyncSession, device: Device
) -> None:
    """A created snapshot round-trips through find_by_id() with its fields intact."""
    command = await _make_command(session, device.id)
    created = await repository.create(
        Snapshot(**snapshot_kwargs(device_id=device.id, command_id=command.id))
    )

    found = await repository.find_by_id(created.id)

    assert found is not None
    assert found.id == created.id
    assert found.filename == "snapshot.jpg"
    assert found.width == 1920


@pytest.mark.asyncio
async def test_repository_find_by_id_returns_none_for_missing(
    repository: SnapshotRepository,
) -> None:
    """Looking up an unknown snapshot UUID returns None rather than raising."""
    assert (await repository.find_by_id(uuid4())) is None


@pytest.mark.asyncio
async def test_repository_find_all_orders_newest_first_and_paginates(
    repository: SnapshotRepository, session: AsyncSession, device: Device
) -> None:
    """Snapshots are listed newest-captured-first, with pagination bounding the page size."""
    now = datetime.now(UTC)
    for index in range(3):
        command = await _make_command(session, device.id)
        await repository.create(
            Snapshot(
                **snapshot_kwargs(
                    device_id=device.id,
                    command_id=command.id,
                    captured_at=now - timedelta(minutes=index),
                )
            )
        )

    page, total = await repository.find_all(device_id=None, offset=0, limit=2)

    assert total == 3
    assert len(page) == 2
    # The oldest capture (index=2, now - 2min) is on the second, un-requested page.
    assert page[0].captured_at > page[1].captured_at


@pytest.mark.asyncio
async def test_repository_find_all_filters_by_device_id(
    repository: SnapshotRepository, session: AsyncSession, device: Device
) -> None:
    """Scoping by device_id excludes snapshots captured by any other device."""
    other_device = await DeviceService(DeviceRepository(session)).register_device(
        DeviceCreate.model_validate(
            {
                "device_name": "other-node",
                "hostname": "other-node.local",
                "display_name": "Other node",
            }
        )
    )
    own_command = await _make_command(session, device.id)
    other_command = await _make_command(session, other_device.id)
    await repository.create(
        Snapshot(**snapshot_kwargs(device_id=device.id, command_id=own_command.id))
    )
    await repository.create(
        Snapshot(**snapshot_kwargs(device_id=other_device.id, command_id=other_command.id))
    )

    page, total = await repository.find_all(device_id=device.id, offset=0, limit=10)

    assert total == 1
    assert [item.device_id for item in page] == [device.id]


@pytest.mark.asyncio
async def test_repository_delete_hard_deletes_the_row(
    repository: SnapshotRepository, session: AsyncSession, device: Device
) -> None:
    """Deleting a snapshot removes the row entirely rather than soft-deleting it."""
    command = await _make_command(session, device.id)
    created = await repository.create(
        Snapshot(**snapshot_kwargs(device_id=device.id, command_id=command.id))
    )

    await repository.delete(created)

    assert (await repository.find_by_id(created.id)) is None
    remaining = (await session.execute(select(Snapshot))).scalars().all()
    assert created.id not in {row.id for row in remaining}


# --- Service -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_record_snapshot_persists_and_returns_entity(
    service: SnapshotService, session: AsyncSession, device: Device
) -> None:
    """record_snapshot persists metadata and returns the full, populated entity."""
    command = await _make_command(session, device.id)

    snapshot = await service.record_snapshot(**snapshot_kwargs(device_id=device.id, command_id=command.id))

    assert snapshot.id is not None
    assert snapshot.device_id == device.id
    assert snapshot.command_id == command.id
    assert snapshot.metadata_ == {}


@pytest.mark.asyncio
async def test_service_record_snapshot_stores_provided_metadata(
    service: SnapshotService, session: AsyncSession, device: Device
) -> None:
    """An explicitly supplied metadata dict is stored rather than defaulted to {}."""
    command = await _make_command(session, device.id)

    snapshot = await service.record_snapshot(
        **snapshot_kwargs(
            device_id=device.id, command_id=command.id, metadata={"trigger": "motion"}
        )
    )

    assert snapshot.metadata_ == {"trigger": "motion"}


@pytest.mark.asyncio
async def test_service_get_snapshot_raises_not_found_for_missing_id(
    service: SnapshotService,
) -> None:
    """Fetching an unknown snapshot UUID raises the domain's not-found error."""
    with pytest.raises(SnapshotNotFound):
        await service.get_snapshot(uuid4())


@pytest.mark.asyncio
async def test_service_get_snapshot_returns_the_recorded_snapshot(
    service: SnapshotService, session: AsyncSession, device: Device
) -> None:
    """The successful get_snapshot path returns the matching entity."""
    command = await _make_command(session, device.id)
    recorded = await service.record_snapshot(
        **snapshot_kwargs(device_id=device.id, command_id=command.id)
    )

    fetched = await service.get_snapshot(recorded.id)

    assert fetched.id == recorded.id


@pytest.mark.asyncio
async def test_service_list_snapshots_delegates_pagination_and_filtering(
    service: SnapshotService, session: AsyncSession, device: Device
) -> None:
    """list_snapshots proxies straight through to the repository's own contract."""
    for _ in range(2):
        command = await _make_command(session, device.id)
        await service.record_snapshot(**snapshot_kwargs(device_id=device.id, command_id=command.id))

    items, total = await service.list_snapshots(device_id=device.id, offset=0, limit=1)

    assert total == 2
    assert len(items) == 1


@pytest.mark.asyncio
async def test_service_delete_snapshot_returns_the_deleted_entity_and_hard_deletes_it(
    service: SnapshotService, session: AsyncSession, device: Device
) -> None:
    """delete_snapshot fetches then hard-deletes, still handing back the deleted entity."""
    command = await _make_command(session, device.id)
    recorded = await service.record_snapshot(
        **snapshot_kwargs(device_id=device.id, command_id=command.id)
    )

    deleted = await service.delete_snapshot(recorded.id)

    assert deleted.id == recorded.id
    with pytest.raises(SnapshotNotFound):
        await service.get_snapshot(recorded.id)


@pytest.mark.asyncio
async def test_service_delete_snapshot_raises_not_found_for_missing_id(
    service: SnapshotService,
) -> None:
    """Deleting an unknown snapshot UUID raises the domain's not-found error."""
    with pytest.raises(SnapshotNotFound):
        await service.delete_snapshot(uuid4())
