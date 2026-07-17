"""Local directory setup for the agent's data/cache/tmp paths."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def ensure_directories(paths: Iterable[Path]) -> None:
    """Create every path (and its parents) if it doesn't already exist."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
