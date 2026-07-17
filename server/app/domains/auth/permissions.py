"""The permission catalog, default roles, and role→permission resolution.

Permissions are plain strings, never an enum or a hardcoded ``if role == ...``
check scattered through the codebase — every authorization decision resolves
through ``permissions_for_roles`` (or a token's already-resolved ``permissions``
claim), so adding a new permission never requires touching a controller.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

#: (name, description) pairs seeded into the `permissions` catalog table.
DEFAULT_PERMISSIONS: Final[tuple[tuple[str, str], ...]] = (
    ("devices.read", "View device registry entries."),
    ("devices.write", "Register, update, enable, or disable devices."),
    ("commands.read", "View command lifecycle state and results."),
    ("commands.execute", "Create, cancel, and progress commands."),
    ("files.read", "Download stored files."),
    ("files.upload", "Upload new files."),
    ("system.admin", "Full administrative access to system configuration."),
)

#: (name, description) pairs seeded into the `roles` table.
DEFAULT_ROLES: Final[tuple[tuple[str, str], ...]] = (
    ("Admin", "Full administrative access to every capability."),
    ("Viewer", "Read-only access across devices, commands, and files."),
    ("Agent", "Device-level access for executing assigned commands and uploading results."),
)

#: The single source of truth for what each default role can do.
ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "Admin": frozenset(name for name, _ in DEFAULT_PERMISSIONS),
    "Viewer": frozenset({"devices.read", "commands.read", "files.read"}),
    "Agent": frozenset({"commands.read", "commands.execute", "files.upload"}),
}


def permissions_for_roles(role_names: Iterable[str]) -> frozenset[str]:
    """Union the permissions granted by every given role name.

    An unrecognized role name grants nothing rather than raising, so a role
    renamed or removed out from under a still-valid token degrades safely.
    """
    granted: set[str] = set()
    for role_name in role_names:
        granted.update(ROLE_PERMISSIONS.get(role_name, frozenset()))
    return frozenset(granted)
