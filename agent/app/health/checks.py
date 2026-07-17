"""Individual health checks: connection, configuration, plugins, memory, disk.

Each check is a plain function taking exactly the dependency it needs — no
hardware checks live here (no GPIO/camera), and memory/disk use stdlib
(``/proc/meminfo``, ``shutil.disk_usage``) rather than an extra dependency,
since the target platform is Linux-only.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from app.config.settings import AgentSettings
from app.health.results import CheckResult, HealthState, combine_states
from app.plugins.registry import PluginManager
from app.services.session import SessionState

DEFAULT_DEGRADED_THRESHOLD = 0.85
DEFAULT_UNHEALTHY_THRESHOLD = 0.95


def check_connection(session: SessionState) -> CheckResult:
    """Healthy when authenticated, degraded when connected but not yet, else unhealthy."""
    if session.connected and session.authenticated:
        return CheckResult(
            name="connection", state=HealthState.HEALTHY, detail="connected and authenticated"
        )
    if session.connected:
        return CheckResult(
            name="connection", state=HealthState.DEGRADED, detail="connected, not authenticated"
        )
    return CheckResult(name="connection", state=HealthState.UNHEALTHY, detail="not connected")


def check_configuration(settings: AgentSettings) -> CheckResult:
    """Healthy once settings have loaded; construction already validated every field."""
    if not settings.device_private_key.get_secret_value().strip():
        return CheckResult(
            name="configuration", state=HealthState.UNHEALTHY, detail="DEVICE_PRIVATE_KEY is empty"
        )
    return CheckResult(name="configuration", state=HealthState.HEALTHY, detail="settings loaded")


def check_plugins(plugin_manager: PluginManager) -> CheckResult:
    """Unhealthy if any registered plugin reports itself unhealthy."""
    results = plugin_manager.check_health()
    unhealthy = [name for name, result in results.items() if not result.healthy]
    if unhealthy:
        return CheckResult(
            name="plugins",
            state=HealthState.UNHEALTHY,
            detail=f"unhealthy: {', '.join(sorted(unhealthy))}",
        )
    return CheckResult(
        name="plugins", state=HealthState.HEALTHY, detail=f"{len(results)} plugin(s) healthy"
    )


def _state_for_fraction(
    used_fraction: float, *, degraded_threshold: float, unhealthy_threshold: float
) -> HealthState:
    if used_fraction >= unhealthy_threshold:
        return HealthState.UNHEALTHY
    if used_fraction >= degraded_threshold:
        return HealthState.DEGRADED
    return HealthState.HEALTHY


def check_memory(
    *,
    meminfo_path: Path = Path("/proc/meminfo"),
    degraded_threshold: float = DEFAULT_DEGRADED_THRESHOLD,
    unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
) -> CheckResult:
    """Parse ``/proc/meminfo`` and report on used-memory fraction."""
    try:
        text = meminfo_path.read_text()
    except OSError as error:
        return CheckResult(
            name="memory",
            state=HealthState.UNHEALTHY,
            detail=f"could not read {meminfo_path}: {error}",
        )
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            values[key.strip()] = int(parts[0])
        except ValueError:
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return CheckResult(
            name="memory", state=HealthState.UNHEALTHY, detail="MemTotal/MemAvailable not found"
        )
    used_fraction = 1 - (available / total)
    state = _state_for_fraction(
        used_fraction,
        degraded_threshold=degraded_threshold,
        unhealthy_threshold=unhealthy_threshold,
    )
    return CheckResult(name="memory", state=state, detail=f"{used_fraction:.1%} used")


def check_disk(
    paths: Sequence[Path],
    *,
    degraded_threshold: float = DEFAULT_DEGRADED_THRESHOLD,
    unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
) -> CheckResult:
    """Report the worst used-space fraction across every configured directory."""
    per_path_states: list[HealthState] = []
    details: list[str] = []
    for path in paths:
        existing = (
            path
            if path.exists()
            else next((parent for parent in path.parents if parent.exists()), Path("/"))
        )
        try:
            usage = shutil.disk_usage(existing)
        except OSError as error:
            per_path_states.append(HealthState.UNHEALTHY)
            details.append(f"{path}: {error}")
            continue
        used_fraction = usage.used / usage.total if usage.total else 0.0
        state = _state_for_fraction(
            used_fraction,
            degraded_threshold=degraded_threshold,
            unhealthy_threshold=unhealthy_threshold,
        )
        per_path_states.append(state)
        details.append(f"{path}: {used_fraction:.1%} used")
    return CheckResult(
        name="disk", state=combine_states(per_path_states), detail="; ".join(details)
    )
