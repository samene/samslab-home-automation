"""Domain-specific failures that API adapters map to stable problem responses."""


class DeviceDomainError(Exception):
    """Base error for failures that are meaningful to Device Registry clients."""


class DeviceAlreadyExists(DeviceDomainError):
    """Raised when an active device already owns a requested device name."""


class DeviceNotFound(DeviceDomainError):
    """Raised when an active device cannot be located."""


class DuplicateCapability(DeviceDomainError):
    """Raised when a capability replacement contains a repeated capability name."""


class InvalidHeartbeat(DeviceDomainError):
    """Raised when heartbeat input violates device lifecycle constraints."""
