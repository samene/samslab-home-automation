"""Domain-specific failures that API adapters map to stable problem responses."""


class SavedMediaDomainError(Exception):
    """Base error for failures that are meaningful to Saved Media domain clients."""


class SavedMediaNotFound(SavedMediaDomainError):
    """Raised when a saved media row cannot be located."""
