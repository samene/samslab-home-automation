"""Domain-specific failures that API adapters map to stable problem responses."""


class ScheduleDomainError(Exception):
    """Base error for failures that are meaningful to Schedules domain clients."""


class ScheduleNotFound(ScheduleDomainError):
    """Raised when a schedule cannot be located."""
