"""Application-layer exceptions: the only errors REST controllers ever handle.

Controllers and the REST layer never import a domain's own exception types
(``DeviceDomainError``, ``CommandDomainError``, ``AuthDomainError``, ...).
Application services catch those and re-raise the equivalent type below via
``translate_domain_error``, so the transport layer stays independent of
domain implementation details.
"""

from __future__ import annotations

from app.application.exceptions.errors import (
    ApplicationError,
    ApplicationValidationError,
    CameraCommandFailedError,
    CameraCommandTimedOutError,
    CameraDeviceNotFoundError,
    CommandNotFoundError,
    ConflictError,
    DeviceAlreadyExistsError,
    DeviceCredentialAlreadyExistsError,
    DeviceCredentialNotFoundError,
    DeviceDisabledError,
    DeviceNotFoundError,
    DisabledAccountError,
    DisabledDeviceError,
    DuplicateCapabilityError,
    ExpiredTokenError,
    ForbiddenError,
    InvalidCommandStateError,
    InvalidCredentialsError,
    InvalidHeartbeatError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    UnauthorizedError,
)
from app.application.exceptions.translation import translate_domain_error

__all__ = [
    "ApplicationError",
    "ApplicationValidationError",
    "CameraCommandFailedError",
    "CameraCommandTimedOutError",
    "CameraDeviceNotFoundError",
    "CommandNotFoundError",
    "ConflictError",
    "DeviceAlreadyExistsError",
    "DeviceCredentialAlreadyExistsError",
    "DeviceCredentialNotFoundError",
    "DeviceDisabledError",
    "DeviceNotFoundError",
    "DisabledAccountError",
    "DisabledDeviceError",
    "DuplicateCapabilityError",
    "ExpiredTokenError",
    "ForbiddenError",
    "InvalidCommandStateError",
    "InvalidCredentialsError",
    "InvalidHeartbeatError",
    "InvalidTokenError",
    "NotFoundError",
    "PermissionDeniedError",
    "UnauthorizedError",
    "translate_domain_error",
]
