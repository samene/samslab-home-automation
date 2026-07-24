"""Tests for NotificationService: dispatch, provider-failure isolation, and status/test flows."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.database import Database
from app.core.s3_client import S3Client
from app.notifications.events import WorkflowCompleted, WorkflowFailed
from app.notifications.models import NotificationLog
from app.notifications.providers.base import NotificationMessage, NotificationResult
from app.notifications.service import NotificationService


class _FakeBody:
    """Mimics boto3's StreamingBody: only ``.read()`` is ever called on it."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeBotoS3Client:
    """A hand-rolled double for the small slice of boto3's S3 client S3Client calls."""

    def __init__(self, *, object_bytes: bytes = b"jpeg-bytes", fail: bool = False) -> None:
        self.object_bytes = object_bytes
        self.fail = fail
        self.get_calls: list[dict[str, object]] = []

    def generate_presigned_url(
        self, client_method: str, *, Params: dict[str, object], ExpiresIn: int
    ) -> str:
        raise NotImplementedError("not exercised by these tests")

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError("not exercised by these tests")

    def get_object(self, **kwargs: object) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("s3 unreachable")
        self.get_calls.append(kwargs)
        return {"Body": _FakeBody(self.object_bytes)}


@dataclass
class FakeProvider:
    """A minimal, in-memory NotificationProvider stand-in for service-level tests."""

    _name: str
    _enabled: bool = True
    _configured: bool = True
    should_fail: bool = False
    should_raise: bool = False
    sent: list[NotificationMessage] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def send(self, message: NotificationMessage) -> NotificationResult:
        self.sent.append(message)
        if self.should_raise:
            raise RuntimeError("provider exploded")
        if self.should_fail:
            return NotificationResult(success=False, duration_seconds=0.01, error_message="boom")
        return NotificationResult(success=True, duration_seconds=0.01)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'notifications.db'}")
    await database.create_schema_for_testing()
    yield database
    await database.dispose()


def _completed_event(**overrides: object) -> WorkflowCompleted:
    values: dict[str, object] = {
        "workflow_id": uuid4(),
        "workflow_name": "Morning Garden",
        "execution_id": uuid4(),
        "started_at": datetime(2026, 1, 1, 9, 15, 21, tzinfo=UTC),
        "completed_at": datetime(2026, 1, 1, 9, 16, 42, tzinfo=UTC),
        "duration_seconds": 81.0,
        "status": "COMPLETED",
        "trigger_source": "Manual",
    }
    values.update(overrides)
    return WorkflowCompleted(**values)  # type: ignore[arg-type]


def _failed_event(**overrides: object) -> WorkflowFailed:
    values: dict[str, object] = {
        "workflow_id": uuid4(),
        "workflow_name": "Morning Garden",
        "execution_id": uuid4(),
        "started_at": datetime(2026, 1, 1, 9, 15, 21, tzinfo=UTC),
        "completed_at": datetime(2026, 1, 1, 9, 15, 53, tzinfo=UTC),
        "duration_seconds": 32.0,
        "status": "FAILED",
        "trigger_source": "Schedule",
        "error_message": "Command ended in status FAILED",
        "failed_step": "camera.snapshot",
    }
    values.update(overrides)
    return WorkflowFailed(**values)  # type: ignore[arg-type]


async def test_notify_workflow_completed_formats_and_sends_the_success_message(
    database: Database,
) -> None:
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider])

    await service.notify_workflow_completed(_completed_event())

    assert len(provider.sent) == 1
    text = provider.sent[0].text
    assert "✅ Workflow Completed" in text
    assert "Morning Garden" in text
    assert "09:15:21" in text
    assert "09:16:42" in text
    assert "81 seconds" in text
    assert "Manual" in text


async def test_notify_workflow_failed_formats_and_sends_the_failure_message(
    database: Database,
) -> None:
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider])

    await service.notify_workflow_failed(_failed_event())

    text = provider.sent[0].text
    assert "❌ Workflow Failed" in text
    assert "Morning Garden" in text
    assert "Take Snapshot" in text  # friendly label for camera.snapshot
    assert "32 seconds" in text
    assert "Command ended in status FAILED" in text


async def test_a_failing_provider_does_not_raise_out_of_notify(database: Database) -> None:
    provider = FakeProvider("telegram", should_fail=True)
    service = NotificationService(database=database, providers=[provider])

    await service.notify_workflow_completed(_completed_event())  # must not raise


async def test_a_provider_that_raises_does_not_raise_out_of_notify(database: Database) -> None:
    """The single most important guarantee: a broken provider must never fail the workflow."""
    provider = FakeProvider("telegram", should_raise=True)
    service = NotificationService(database=database, providers=[provider])

    await service.notify_workflow_failed(_failed_event())  # must not raise


async def test_dispatch_records_a_notification_log_row(database: Database) -> None:
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider])
    event = _completed_event()

    await service.notify_workflow_completed(event)

    async with database.session_factory() as session:
        rows = (await session.execute(select(NotificationLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider == "telegram"
    assert rows[0].event_type == "WORKFLOW_COMPLETED"
    assert rows[0].success is True
    assert rows[0].workflow_id == event.workflow_id
    assert rows[0].workflow_name == "Morning Garden"


async def test_dispatch_records_a_failure_log_row_with_the_error_message(
    database: Database,
) -> None:
    provider = FakeProvider("telegram", should_fail=True)
    service = NotificationService(database=database, providers=[provider])

    await service.notify_workflow_completed(_completed_event())

    async with database.session_factory() as session:
        row = (await session.execute(select(NotificationLog))).scalar_one()
    assert row.success is False
    assert row.error_message == "boom"


async def test_service_works_with_no_database_configured() -> None:
    """Notification delivery must not depend on a database — only the history log does."""
    provider = FakeProvider("telegram")
    service = NotificationService(database=None, providers=[provider])

    await service.notify_workflow_completed(_completed_event())  # must not raise

    assert len(provider.sent) == 1


async def test_send_test_notification_requires_no_workflow(database: Database) -> None:
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider])

    results = await service.send_test_notification()

    assert len(results) == 1
    assert results[0].provider == "telegram"
    assert results[0].success is True
    assert "Test Notification" in provider.sent[0].text


async def test_send_test_notification_reports_provider_failure(database: Database) -> None:
    provider = FakeProvider("telegram", should_fail=True)
    service = NotificationService(database=database, providers=[provider])

    results = await service.send_test_notification()

    assert results[0].success is False
    assert results[0].error_message == "boom"


async def test_get_status_reports_every_providers_configuration(database: Database) -> None:
    provider = FakeProvider("telegram", _enabled=True, _configured=False)
    service = NotificationService(database=database, providers=[provider])

    status = await service.get_status()

    assert len(status.providers) == 1
    assert status.providers[0].provider == "telegram"
    assert status.providers[0].enabled is True
    assert status.providers[0].configured is False
    assert status.providers[0].last_attempt_at is None


async def test_get_status_reflects_the_most_recent_delivery_attempt(database: Database) -> None:
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider])
    await service.notify_workflow_completed(_completed_event())

    status = await service.get_status()

    assert status.providers[0].last_attempt_at is not None
    assert status.providers[0].last_success is True


async def test_dispatches_to_every_registered_provider_independently(database: Database) -> None:
    telegram = FakeProvider("telegram", should_fail=False)
    other = FakeProvider("future-provider", should_fail=True)
    service = NotificationService(database=database, providers=[telegram, other])

    results = await service.send_test_notification()

    assert {r.provider: r.success for r in results} == {"telegram": True, "future-provider": False}


async def test_notify_workflow_completed_attaches_the_thumbnail_as_photo_bytes(
    database: Database,
) -> None:
    """No S3 presigned URL is ever minted — a direct GetObject fetch, shared with the provider."""
    boto_client = FakeBotoS3Client(object_bytes=b"\xff\xd8real-jpeg-bytes")
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)
    event = _completed_event(thumbnail_object_key="thumbnails/snapshot.jpg")

    await service.notify_workflow_completed(event)

    assert provider.sent[0].photo_bytes == b"\xff\xd8real-jpeg-bytes"
    assert provider.sent[0].photo_filename == "Morning Garden.jpg"
    assert boto_client.get_calls == [{"Bucket": "samslab-media", "Key": "thumbnails/snapshot.jpg"}]


async def test_notify_workflow_completed_sends_text_only_when_no_thumbnail(
    database: Database,
) -> None:
    boto_client = FakeBotoS3Client()
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)

    await service.notify_workflow_completed(_completed_event(thumbnail_object_key=None))

    assert provider.sent[0].photo_bytes is None
    assert boto_client.get_calls == []


async def test_notify_workflow_completed_sends_text_only_when_no_s3_client_configured(
    database: Database,
) -> None:
    """A workflow can have a thumbnail while S3 access itself is unconfigured server-wide."""
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=None)

    await service.notify_workflow_completed(
        _completed_event(thumbnail_object_key="thumbnails/snapshot.jpg")
    )  # must not raise

    assert provider.sent[0].photo_bytes is None


async def test_notify_workflow_completed_falls_back_to_text_when_the_thumbnail_fetch_fails(
    database: Database,
) -> None:
    """A broken S3 fetch must never lose the notification entirely — text still sends."""
    boto_client = FakeBotoS3Client(fail=True)
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)

    await service.notify_workflow_completed(
        _completed_event(thumbnail_object_key="thumbnails/snapshot.jpg")
    )

    assert provider.sent[0].photo_bytes is None
    assert provider.sent[0].text  # the text message still went out


async def test_notify_workflow_completed_attaches_the_recording_as_video_bytes(
    database: Database,
) -> None:
    """No S3 presigned URL is ever minted — a direct GetObject fetch, shared with the provider."""
    boto_client = FakeBotoS3Client(object_bytes=b"\x00\x00\x00\x18ftypmp42real-mp4-bytes")
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)
    event = _completed_event(
        thumbnail_object_key=None,
        video_object_key="originals/recording.mp4",
        video_filename="recording.mp4",
        video_size_bytes=5_000_000,
        video_width=1920,
        video_height=1080,
        video_duration_seconds=42,
    )

    await service.notify_workflow_completed(event)

    assert provider.sent[0].video_bytes == b"\x00\x00\x00\x18ftypmp42real-mp4-bytes"
    assert provider.sent[0].video_filename == "recording.mp4"
    assert provider.sent[0].video_width == 1920
    assert provider.sent[0].video_height == 1080
    assert provider.sent[0].video_duration_seconds == 42
    assert provider.sent[0].photo_bytes is None
    assert boto_client.get_calls == [{"Bucket": "samslab-media", "Key": "originals/recording.mp4"}]


async def test_notify_workflow_completed_falls_back_to_default_video_filename(
    database: Database,
) -> None:
    boto_client = FakeBotoS3Client(object_bytes=b"mp4-bytes")
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)
    event = _completed_event(
        thumbnail_object_key=None,
        video_object_key="originals/recording.mp4",
        video_filename=None,
        video_size_bytes=5_000_000,
    )

    await service.notify_workflow_completed(event)

    assert provider.sent[0].video_filename == "Morning Garden.mp4"


async def test_notify_workflow_completed_skips_a_video_over_the_telegram_upload_limit(
    database: Database,
) -> None:
    """Checked against the size already on the event — no S3 call for an attachment
    that Telegram would reject anyway."""
    boto_client = FakeBotoS3Client(object_bytes=b"should never be fetched")
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)
    event = _completed_event(
        thumbnail_object_key=None,
        video_object_key="originals/huge-recording.mp4",
        video_filename="huge-recording.mp4",
        video_size_bytes=80 * 1024 * 1024,
    )

    await service.notify_workflow_completed(event)

    assert provider.sent[0].video_bytes is None
    assert boto_client.get_calls == []
    assert "80 MB" in provider.sent[0].text
    assert "50 MB" in provider.sent[0].text


async def test_notify_workflow_completed_falls_back_to_text_when_the_video_fetch_fails(
    database: Database,
) -> None:
    """A broken S3 fetch must never lose the notification entirely — text still sends."""
    boto_client = FakeBotoS3Client(fail=True)
    s3_client = S3Client(client=boto_client, bucket="samslab-media")
    provider = FakeProvider("telegram")
    service = NotificationService(database=database, providers=[provider], s3_client=s3_client)

    await service.notify_workflow_completed(
        _completed_event(
            thumbnail_object_key=None,
            video_object_key="originals/recording.mp4",
            video_filename="recording.mp4",
            video_size_bytes=5_000_000,
        )
    )

    assert provider.sent[0].video_bytes is None
    assert provider.sent[0].text  # the text message still went out
