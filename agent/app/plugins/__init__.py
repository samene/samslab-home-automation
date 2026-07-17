"""A lightweight plugin framework: capabilities, startup/shutdown hooks, health checks.

No real plugin exists yet — future GPIO/camera/scheduler drivers register
against ``Plugin`` and are loaded through a ``PluginManager``.
"""

from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.registry import PluginManager

__all__ = ["Plugin", "PluginHealthCheck", "PluginManager"]
