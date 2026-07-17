"""Translate domain exceptions into their application-layer equivalent.

Every application service catches its domain services' exception base class
(e.g. ``DeviceDomainError``) and calls ``translate_domain_error`` rather than
re-raising the domain type, so REST never needs to know a domain exists.
"""

from __future__ import annotations

from app.application.exceptions.errors import (
    ApplicationError,
    CommandNotFoundError,
    DeviceAlreadyExistsError,
    DeviceCredentialAlreadyExistsError,
    DeviceCredentialNotFoundError,
    DeviceNotFoundError,
    DisabledAccountError,
    DisabledDeviceError,
    DuplicateCapabilityError,
    ExpiredTokenError,
    InvalidCommandStateError,
    InvalidCredentialsError,
    InvalidHeartbeatError,
    InvalidTokenError,
    PermissionDeniedError,
)
from app.domains.auth.exceptions import (
    DeviceCredentialAlreadyExists,
    DeviceCredentialNotFound,
    DisabledAccount,
    DisabledDevice,
    ExpiredToken,
    InvalidCredentials,
    InvalidToken,
    PermissionDenied,
)
from app.domains.commands.exceptions import CommandNotFound, InvalidStateTransition
from app.domains.devices.exceptions import (
    DeviceAlreadyExists,
    DeviceNotFound,
    DuplicateCapability,
    InvalidHeartbeat,
)

_TRANSLATIONS: dict[type[Exception], type[ApplicationError]] = {
    DeviceAlreadyExists: DeviceAlreadyExistsError,
    DeviceNotFound: DeviceNotFoundError,
    DuplicateCapability: DuplicateCapabilityError,
    InvalidHeartbeat: InvalidHeartbeatError,
    CommandNotFound: CommandNotFoundError,
    InvalidStateTransition: InvalidCommandStateError,
    InvalidCredentials: InvalidCredentialsError,
    ExpiredToken: ExpiredTokenError,
    InvalidToken: InvalidTokenError,
    PermissionDenied: PermissionDeniedError,
    DisabledAccount: DisabledAccountError,
    DisabledDevice: DisabledDeviceError,
    DeviceCredentialNotFound: DeviceCredentialNotFoundError,
    DeviceCredentialAlreadyExists: DeviceCredentialAlreadyExistsError,
}


def translate_domain_error(error: Exception) -> ApplicationError:
    """Map one known domain exception instance to its application exception.

    Falls back to the generic ``ApplicationError`` for any domain exception
    type not explicitly mapped, so an unmapped failure still surfaces as a
    safe, generic problem response instead of an unhandled 500.
    """
    application_type = _TRANSLATIONS.get(type(error), ApplicationError)
    return application_type(str(error))
