"""The three ``camera.*`` command handlers: start, stop, status.

Stateless, exactly like the built-in ``system.*`` handlers — everything a
handler needs arrives through ``CommandContext.services.camera_service``.
``CameraService``'s own methods do blocking I/O (opening the camera, spawning
ffmpeg, joining a thread), so every handler here hands off to a thread-pool
executor rather than calling them directly on the event loop.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Mapping
from typing import Any

from app.commands.context import CommandContext
from app.commands.handler import CommandHandler
from app.commands.registry import CommandRegistry
from app.plugins.camera.exceptions import CameraUnavailableError

#: Starting the camera/ffmpeg can take longer than the default 30s on a slow Pi.
_STREAM_START_TIMEOUT_SECONDS = 45.0
#: Opening a fresh (non-streaming) camera session plus two S3 uploads can
#: also exceed the default 30s, especially over a slow uplink.
_SNAPSHOT_TIMEOUT_SECONDS = 60.0
#: Opening a fresh recording session is otherwise as fast as a snapshot's own start.
_RECORD_START_TIMEOUT_SECONDS = 45.0
#: Finalizing a local MP4 and uploading it can take minutes for a large file.
_RECORD_STOP_TIMEOUT_SECONDS = 900.0


class CameraStreamStartHandler(CommandHandler):
    """Starts the live stream, or confirms it's already running."""

    @property
    def command_type(self) -> str:
        return "camera.stream.start"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required; resolution/fps come from agent configuration.

        An optional ``mediamtx_publish_token`` may be present — a MediaMTX
        JWT minted server-side, required once a deployment sets MediaMTX's
        authMethod to ``jwt`` (see ``CameraService.start``).
        """

    def timeout(self) -> float:
        return _STREAM_START_TIMEOUT_SECONDS

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        camera_service = context.services.camera_service
        publish_token = arguments.get("mediamtx_publish_token")
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, functools.partial(camera_service.start, publish_token=publish_token)
            )
        except CameraUnavailableError as error:
            context.logger.warning(
                "camera_stream_start_failed",
                command_id=str(context.command_id),
                error=str(error),
            )
            raise
        context.logger.info(
            "camera_stream_started",
            command_id=str(context.command_id),
            stream_name=result["stream_name"],
            publish_url=camera_service.redacted_publish_url(),
            playback_url=result["playback_url"],
            resolution=result["resolution"],
            fps=result["fps"],
        )
        return {
            "stream_name": result["stream_name"],
            "playback_url": result["playback_url"],
            "resolution": result["resolution"],
            "fps": result["fps"],
            "started_at": result["started_at"],
        }


class CameraStreamStopHandler(CommandHandler):
    """Stops the live stream, or confirms it's already stopped."""

    @property
    def command_type(self) -> str:
        return "camera.stream.stop"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        camera_service = context.services.camera_service
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, camera_service.stop)
        context.logger.info(
            "camera_stream_stopped",
            command_id=str(context.command_id),
            stream_name=camera_service.status()["stream_name"],
            duration=result["duration"],
            frames_sent=result["frames_sent"],
        )
        return {
            "duration": result["duration"],
            "frames_sent": result["frames_sent"],
            "stopped_at": result["stopped_at"],
        }


class CameraStatusHandler(CommandHandler):
    """Reports the live stream's current state without changing it."""

    @property
    def command_type(self) -> str:
        return "camera.status"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        camera_service = context.services.camera_service
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, camera_service.status)
        return {
            "running": result["running"],
            "uptime": result["uptime_seconds"],
            "stream_name": result["stream_name"],
            "playback_url": result["playback_url"],
        }


class CameraSnapshotHandler(CommandHandler):
    """Captures one high-resolution still image and uploads it to S3.

    Independent of streaming — see ``CameraService.capture_snapshot`` for the
    reuse-live-session-or-open-fresh-one behavior; this handler is a thin,
    stateless offload to it, exactly like the other three ``camera.*``
    handlers.
    """

    @property
    def command_type(self) -> str:
        return "camera.snapshot"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    def timeout(self) -> float:
        return _SNAPSHOT_TIMEOUT_SECONDS

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        camera_service = context.services.camera_service
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, camera_service.capture_snapshot)
        except CameraUnavailableError as error:
            context.logger.warning(
                "camera_snapshot_failed",
                command_id=str(context.command_id),
                correlation_id=str(context.correlation_id),
                error=str(error),
            )
            raise
        context.logger.info(
            "camera_snapshot_captured",
            command_id=str(context.command_id),
            correlation_id=str(context.correlation_id),
            capture_duration=result["capture_duration"],
            upload_duration=result["upload_duration"],
            resolution=f"{result['width']}x{result['height']}",
            size=result["size"],
            bucket=result["bucket"],
            original_object_key=result["original_object_key"],
            thumbnail_object_key=result["thumbnail_object_key"],
            reused_stream=result["reused_stream"],
        )
        return {
            "bucket": result["bucket"],
            "filename": result["filename"],
            "original_object_key": result["original_object_key"],
            "thumbnail_object_key": result["thumbnail_object_key"],
            "etag": result["etag"],
            "sha256": result["sha256"],
            "width": result["width"],
            "height": result["height"],
            "size": result["size"],
            "captured_at": result["captured_at"],
        }


class CameraRecordStartHandler(CommandHandler):
    """Starts local, high-quality MP4 recording, or confirms it's already active.

    Independent of streaming — see ``CameraService.start_recording`` for why
    this fails (rather than sharing hardware) if a live stream is active;
    this handler is a thin, stateless offload to it, exactly like the other
    ``camera.*`` handlers.
    """

    @property
    def command_type(self) -> str:
        return "camera.record.start"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    def timeout(self) -> float:
        return _RECORD_START_TIMEOUT_SECONDS

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        camera_service = context.services.camera_service
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, camera_service.start_recording)
        except CameraUnavailableError as error:
            context.logger.warning(
                "camera_record_start_failed",
                command_id=str(context.command_id),
                error=str(error),
            )
            raise
        context.logger.info(
            "camera_recording_started",
            command_id=str(context.command_id),
            filename=result["filename"],
            resolution=f"{result['width']}x{result['height']}",
            fps=result["fps"],
        )
        return {
            "status": result["status"],
            "filename": result["filename"],
            "width": result["width"],
            "height": result["height"],
            "fps": result["fps"],
            "started_at": result["started_at"],
        }


class CameraRecordStopHandler(CommandHandler):
    """Stops recording, finalizes the MP4, and uploads it directly to S3."""

    @property
    def command_type(self) -> str:
        return "camera.record.stop"

    async def validate(self, context: CommandContext, arguments: Mapping[str, Any]) -> None:
        """No arguments are required."""

    def timeout(self) -> float:
        return _RECORD_STOP_TIMEOUT_SECONDS

    async def execute(
        self, context: CommandContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        camera_service = context.services.camera_service
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, camera_service.stop_recording)
        except CameraUnavailableError as error:
            context.logger.warning(
                "camera_record_stop_failed",
                command_id=str(context.command_id),
                correlation_id=str(context.correlation_id),
                error=str(error),
            )
            raise
        context.logger.info(
            "camera_recording_finished",
            command_id=str(context.command_id),
            correlation_id=str(context.correlation_id),
            duration=result["duration"],
            upload_duration=result["upload_duration"],
            resolution=f"{result['width']}x{result['height']}",
            file_size=result["file_size"],
            bucket=result["bucket"],
            object_key=result["object_key"],
        )
        return {
            "bucket": result["bucket"],
            "filename": result["filename"],
            "object_key": result["object_key"],
            "thumbnail_object_key": result["thumbnail_object_key"],
            "etag": result["etag"],
            "sha256": result["sha256"],
            "width": result["width"],
            "height": result["height"],
            "duration": result["duration"],
            "fps": result["fps"],
            "bitrate": result["bitrate"],
            "file_size": result["file_size"],
            "recorded_at": result["recorded_at"],
            "upload_duration": result["upload_duration"],
        }


def register_camera_handlers(registry: CommandRegistry) -> None:
    """Register every ``camera.*`` handler onto ``registry``."""
    registry.register(CameraStreamStartHandler())
    registry.register(CameraStreamStopHandler())
    registry.register(CameraStatusHandler())
    registry.register(CameraSnapshotHandler())
    registry.register(CameraRecordStartHandler())
    registry.register(CameraRecordStopHandler())
