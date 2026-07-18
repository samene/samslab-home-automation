"""Domain-specific failures that API adapters map to stable problem responses."""


class SnapshotDomainError(Exception):
    """Base error for failures that are meaningful to Snapshots domain clients."""


class SnapshotNotFound(SnapshotDomainError):
    """Raised when a snapshot cannot be located."""
