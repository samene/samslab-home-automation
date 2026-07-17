"""systemd-friendly process concerns: signal handling and local directory setup."""

from app.system.directories import ensure_directories
from app.system.signals import DEFAULT_SHUTDOWN_SIGNALS, install_shutdown_handlers

__all__ = ["DEFAULT_SHUTDOWN_SIGNALS", "ensure_directories", "install_shutdown_handlers"]
