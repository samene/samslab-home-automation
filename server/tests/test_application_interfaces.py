"""Tests confirming the application layer's future-facing interfaces are well-formed ABCs.

No concrete production implementation exists for any of these yet — that is
intentional (see ``app/application/interfaces/__init__.py``). These tests
exercise the *contracts* themselves: each is abstract until fully implemented,
and a conforming implementation satisfies it. None of this wires a real
adapter into any application service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.interfaces import (
    AuditRecorder,
    Clock,
    CurrentUserProvider,
    IdGenerator,
    NotificationSender,
    ObjectStorage,
    UnitOfWork,
)


@pytest.mark.parametrize(
    "interface",
    [
        Clock,
        IdGenerator,
        ObjectStorage,
        NotificationSender,
        AuditRecorder,
        CurrentUserProvider,
        UnitOfWork,
    ],
)
def test_interface_cannot_be_instantiated_without_an_implementation(interface: type) -> None:
    """Every interface is a true ABC: it cannot be instantiated directly."""
    with pytest.raises(TypeError):
        interface()


class _FixedClock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


def test_clock_implementation_satisfies_the_contract() -> None:
    """A concrete Clock can be instantiated and queried."""
    assert _FixedClock().now() == datetime(2026, 1, 1, tzinfo=UTC)


class _SequentialIdGenerator(IdGenerator):
    def __init__(self) -> None:
        self._next = uuid4()

    def new_id(self) -> UUID:
        return self._next


def test_id_generator_implementation_satisfies_the_contract() -> None:
    """A concrete IdGenerator can be instantiated and produces a UUID."""
    generator = _SequentialIdGenerator()
    assert isinstance(generator.new_id(), UUID)


class _InMemoryObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> str:
        self._objects[key] = data
        return key

    async def get(self, key: str) -> bytes:
        return self._objects[key]

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)


@pytest.mark.asyncio
async def test_object_storage_implementation_satisfies_the_contract() -> None:
    """A concrete ObjectStorage round-trips put/get/delete."""
    storage = _InMemoryObjectStorage()
    await storage.put("key", b"data")
    assert await storage.get("key") == b"data"
    await storage.delete("key")
    assert "key" not in storage._objects


class _RecordingNotificationSender(NotificationSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(
        self, *, recipient: str, message: str, context: dict[str, Any] | None = None
    ) -> None:
        self.sent.append((recipient, message))


@pytest.mark.asyncio
async def test_notification_sender_implementation_satisfies_the_contract() -> None:
    """A concrete NotificationSender records what it was asked to send."""
    sender = _RecordingNotificationSender()
    await sender.send(recipient="ops@example.com", message="test")
    assert sender.sent == [("ops@example.com", "test")]


class _RecordingAuditRecorder(AuditRecorder):
    def __init__(self) -> None:
        self.records: list[tuple[str | None, str]] = []

    async def record(
        self, *, actor: str | None, action: str, context: dict[str, Any] | None = None
    ) -> None:
        self.records.append((actor, action))


@pytest.mark.asyncio
async def test_audit_recorder_implementation_satisfies_the_contract() -> None:
    """A concrete AuditRecorder records the actor and action it was given."""
    recorder = _RecordingAuditRecorder()
    await recorder.record(actor="operator", action="device.disable")
    assert recorder.records == [("operator", "device.disable")]


class _AnonymousCurrentUserProvider(CurrentUserProvider):
    def get_user_id(self) -> str | None:
        return None


def test_current_user_provider_implementation_satisfies_the_contract() -> None:
    """A concrete CurrentUserProvider may report no authenticated caller."""
    assert _AnonymousCurrentUserProvider().get_user_id() is None


class _NoOpUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _NoOpUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_unit_of_work_implementation_commits_on_success() -> None:
    """A concrete UnitOfWork used as an async context manager can commit."""
    uow = _NoOpUnitOfWork()
    async with uow:
        await uow.commit()
    assert uow.committed is True
    assert uow.rolled_back is False


@pytest.mark.asyncio
async def test_unit_of_work_implementation_rolls_back_on_exception() -> None:
    """A concrete UnitOfWork rolls back when its block raises."""
    uow = _NoOpUnitOfWork()
    with pytest.raises(ValueError):
        async with uow:
            raise ValueError("boom")
    assert uow.rolled_back is True
    assert uow.committed is False
