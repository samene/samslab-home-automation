"""Domain-specific failures that API adapters map to stable problem responses.

Cross-domain failures (e.g. a command referencing a missing or disabled device)
are not modeled here — that check is a cross-domain concern owned by the
application layer, never by this domain in isolation.
"""


class CommandDomainError(Exception):
    """Base error for failures that are meaningful to Command domain clients."""


class CommandNotFound(CommandDomainError):
    """Raised when a command cannot be located."""


class InvalidStateTransition(CommandDomainError):
    """Raised when a requested lifecycle transition violates the state machine."""
