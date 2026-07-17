"""Domain-specific failures that API adapters map to stable problem responses."""


class AuthDomainError(Exception):
    """Base error for failures that are meaningful to Auth domain clients."""


class InvalidCredentials(AuthDomainError):
    """Raised for any login/device-token failure; never distinguishes the exact cause."""


class ExpiredToken(AuthDomainError):
    """Raised when a JWT's ``exp`` claim has passed (beyond allowed clock skew)."""


class InvalidToken(AuthDomainError):
    """Raised when a token is malformed, mis-signed, or of the wrong principal type."""


class PermissionDenied(AuthDomainError):
    """Raised when an authenticated principal lacks a required role or permission."""


class DisabledAccount(AuthDomainError):
    """Raised when a user account exists but is disabled."""


class DisabledDevice(AuthDomainError):
    """Raised when a device credential exists but is disabled."""


class DeviceCredentialNotFound(AuthDomainError):
    """Raised when a device has no credential to rotate."""


class DeviceCredentialAlreadyExists(AuthDomainError):
    """Raised when issuing a credential for a device that already has one."""
