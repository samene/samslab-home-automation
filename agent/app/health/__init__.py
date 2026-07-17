"""Local health subsystem: connection, configuration, plugins, memory, disk. No hardware checks."""

from app.health.checks import (
    check_configuration,
    check_connection,
    check_disk,
    check_memory,
    check_plugins,
)
from app.health.results import CheckResult, HealthReport, HealthState, combine_states
from app.health.service import HealthService

__all__ = [
    "CheckResult",
    "HealthReport",
    "HealthService",
    "HealthState",
    "check_configuration",
    "check_connection",
    "check_disk",
    "check_memory",
    "check_plugins",
    "combine_states",
]
