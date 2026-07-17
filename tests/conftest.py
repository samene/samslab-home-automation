"""Shared fixtures for the end-to-end verification framework.

Every test gets its own fresh ``ServerHarness`` — a real server on a real
port with its own temp-file SQLite database — for full isolation, matching
the existing ``server/tests`` convention of a fresh ``app``/``Database`` per
test rather than a shared session-scoped instance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.utils.server_harness import ServerHarness, default_test_settings, run_server


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[ServerHarness]:
    """A real, running Sam's Lab server with a fresh SQLite database."""
    settings = default_test_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}")
    async with run_server(settings) as harness:
        yield harness
