"""Runs every health check and combines them into one report."""

from __future__ import annotations

from app.config.settings import AgentSettings
from app.health.checks import (
    check_configuration,
    check_connection,
    check_disk,
    check_memory,
    check_plugins,
)
from app.health.results import HealthReport, combine_states
from app.plugins.registry import PluginManager
from app.services.session import SessionState


class HealthService:
    """Dependency-injected health subsystem: no global state, no hardware checks."""

    def __init__(
        self,
        *,
        settings: AgentSettings,
        session: SessionState,
        plugin_manager: PluginManager,
    ) -> None:
        self._settings = settings
        self._session = session
        self._plugin_manager = plugin_manager

    def check(self) -> HealthReport:
        """Run connection, configuration, plugins, memory, and disk checks."""
        checks = (
            check_connection(self._session),
            check_configuration(self._settings),
            check_plugins(self._plugin_manager),
            check_memory(),
            check_disk(
                [
                    self._settings.local_data_directory,
                    self._settings.cache_directory,
                    self._settings.tmp_directory,
                ]
            ),
        )
        return HealthReport(state=combine_states(check.state for check in checks), checks=checks)
