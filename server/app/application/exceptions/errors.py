"""The application-layer exception hierarchy.

Five broad categories cover every failure a use case can report; REST maps
each category to one HTTP status regardless of which domain raised the
original error, keeping that mapping in exactly one place (``app.main``).
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base error for every failure an application service can report to REST."""


class NotFoundError(ApplicationError):
    """The referenced resource does not exist. Maps to HTTP 404."""


class ConflictError(ApplicationError):
    """The request is well-formed but conflicts with current resource state. Maps to HTTP 409."""


class ApplicationValidationError(ApplicationError):
    """The request failed a use-case-level validation rule. Maps to HTTP 422."""


class UnauthorizedError(ApplicationError):
    """Authentication is missing, invalid, or expired. Maps to HTTP 401."""


class ForbiddenError(ApplicationError):
    """Authenticated but not permitted to perform this action. Maps to HTTP 403."""


# --- Device use cases -------------------------------------------------------


class DeviceNotFoundError(NotFoundError):
    """Raised when a referenced device does not exist."""


class DeviceAlreadyExistsError(ConflictError):
    """Raised when a device name is already registered."""


class DeviceDisabledError(ConflictError):
    """Raised when an operation requires a device that is currently disabled."""


class DuplicateCapabilityError(ConflictError):
    """Raised when a capability replacement contains a repeated capability name."""


class InvalidHeartbeatError(ApplicationValidationError):
    """Raised when heartbeat input violates device lifecycle constraints."""


# --- Command use cases -------------------------------------------------------


class CommandNotFoundError(NotFoundError):
    """Raised when a referenced command does not exist."""


class InvalidCommandStateError(ConflictError):
    """Raised when a requested lifecycle transition violates the command state machine."""


# --- Auth use cases -----------------------------------------------------------


class InvalidCredentialsError(UnauthorizedError):
    """Raised for any login or device-token failure; never distinguishes the exact cause."""


class ExpiredTokenError(UnauthorizedError):
    """Raised when a bearer token's ``exp`` claim has passed."""


class InvalidTokenError(UnauthorizedError):
    """Raised when a bearer token is malformed, mis-signed, or the wrong principal type."""


class DisabledAccountError(UnauthorizedError):
    """Raised when a user account exists but is disabled."""


class DisabledDeviceError(UnauthorizedError):
    """Raised when a device credential exists but is disabled."""


class PermissionDeniedError(ForbiddenError):
    """Raised when an authenticated principal lacks a required role or permission."""


class DeviceCredentialNotFoundError(NotFoundError):
    """Raised when a device has no credential to rotate."""


class DeviceCredentialAlreadyExistsError(ConflictError):
    """Raised when issuing a credential for a device that already has one."""


# --- Camera use cases ---------------------------------------------------------


class CameraDeviceNotFoundError(NotFoundError):
    """Raised when no registered device exists to target a camera command at."""


class CameraCommandFailedError(ConflictError):
    """Raised when a ``camera.stream.*`` command does not complete successfully."""


class CameraCommandTimedOutError(ConflictError):
    """Raised when a ``camera.stream.*`` command does not reach a terminal state in time."""
