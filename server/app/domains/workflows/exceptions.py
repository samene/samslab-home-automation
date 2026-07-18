"""Domain-specific failures that API adapters map to stable problem responses."""


class WorkflowDomainError(Exception):
    """Base error for failures that are meaningful to Workflows domain clients."""


class WorkflowNotFound(WorkflowDomainError):
    """Raised when a workflow cannot be located."""
