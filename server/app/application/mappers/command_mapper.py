"""Mapping from Command domain persistence entities to application DTOs."""

from __future__ import annotations

from app.application.dto.command_dto import (
    CommandDetailDTO,
    CommandDTO,
    CommandEventDTO,
    CommandResultDTO,
)
from app.domains.commands.models import Command, CommandEvent, CommandResult


def to_command_result_dto(result: CommandResult) -> CommandResultDTO:
    """Map one persisted command result to its DTO."""
    return CommandResultDTO(
        id=result.id,
        success=result.success,
        exit_code=result.exit_code,
        result=result.result,
        error_message=result.error_message,
        duration_ms=result.duration_ms,
        completed_at=result.completed_at,
    )


def to_command_event_dto(event: CommandEvent) -> CommandEventDTO:
    """Map one persisted lifecycle event to its DTO."""
    return CommandEventDTO(
        id=event.id, event_type=event.event_type, timestamp=event.timestamp, details=event.details
    )


def to_command_dto(command: Command) -> CommandDTO:
    """Map a persisted command to its lightweight, list-friendly DTO."""
    return CommandDTO(
        id=command.id,
        device_id=command.device_id,
        command_type=command.command_type,
        status=command.status,
        priority=command.priority,
        payload=command.payload,
        requested_by=command.requested_by,
        created_at=command.created_at,
        scheduled_at=command.scheduled_at,
        started_at=command.started_at,
        completed_at=command.completed_at,
        expires_at=command.expires_at,
        correlation_id=command.correlation_id,
        trace_id=command.trace_id,
        retry_count=command.retry_count,
        max_retries=command.max_retries,
    )


def to_command_detail_dto(command: Command) -> CommandDetailDTO:
    """Map a persisted command to its full DTO, including result and event trail."""
    return CommandDetailDTO(
        **to_command_dto(command).model_dump(),
        result=to_command_result_dto(command.result) if command.result else None,
        events=[to_command_event_dto(event) for event in command.events],
    )
