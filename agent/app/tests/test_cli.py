"""Tests for the samslab-agent CLI: version/health/config/validate-config/start."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

import pytest

from app.cli.main import main
from app.config.settings import AgentSettings

# ``app.cli``'s own __init__ rebinds its ``main`` attribute to this function
# (via ``from app.cli.main import main``), which would shadow the submodule if
# accessed as ``app.cli.main`` — pull the real submodule from sys.modules instead.
cli_main = sys.modules["app.cli.main"]

_BASE_ARGS = [
    "--server-url",
    "ws://localhost:8000/ws",
    "--device-name",
    "cli-test-device",
    "--device-client-id",
    "cli-test-client-id",
    "--device-private-key",
    "cli-test-private-key",
    "--auth-token-url",
    "http://localhost:8000/auth/device/token",
]


def test_version_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    """`samslab-agent version` prints the agent's version and exits 0."""
    exit_code = main(["version"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.strip()


def test_config_prints_resolved_settings_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    """`samslab-agent config` prints the resolved settings, with the token masked."""
    exit_code = main(["config", *_BASE_ARGS])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["device_name"] == "cli-test-device"
    assert "cli-test-private-key" not in out


def test_validate_config_succeeds_for_valid_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`samslab-agent validate-config` exits 0 and prints a confirmation for valid settings."""
    exit_code = main(["validate-config", *_BASE_ARGS])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "valid" in out.lower()


def test_validate_config_fails_for_invalid_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An invalid SERVER_URL causes validate-config to exit non-zero."""
    exit_code = main(
        [
            "validate-config",
            "--server-url",
            "http://not-a-websocket",
            "--device-name",
            "cli-test-device",
            "--device-client-id",
            "cli-test-client-id",
            "--device-private-key",
            "cli-test-private-key",
            "--auth-token-url",
            "http://localhost:8000/auth/device/token",
        ]
    )
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Invalid configuration" in err


def test_health_prints_json_report_and_nonzero_exit_when_disconnected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`samslab-agent health` reports UNHEALTHY (never connected) with a non-zero exit."""
    exit_code = main(["health", *_BASE_ARGS])
    out = capsys.readouterr().out

    payload = json.loads(out)
    assert payload["state"] == "UNHEALTHY"
    assert exit_code == 2


def test_main_requires_a_subcommand() -> None:
    """Calling with no subcommand exits via argparse's required-subparser error."""
    with pytest.raises(SystemExit):
        main([])


def test_cmd_start_wires_and_runs_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`samslab-agent start` configures logging/directories and runs the built agent."""
    calls: dict[str, bool] = {
        "configure_logging": False,
        "ensure_directories": False,
        "install_shutdown_handlers": False,
        "run": False,
    }

    class FakeAgent:
        def request_stop(self) -> None:
            pass

        async def run(self) -> None:
            calls["run"] = True

    def fake_build_agent(settings: AgentSettings) -> FakeAgent:
        return FakeAgent()

    def fake_configure_logging(settings: AgentSettings) -> None:
        calls["configure_logging"] = True

    def fake_ensure_directories(paths: Sequence[object]) -> None:
        calls["ensure_directories"] = True

    def fake_install_shutdown_handlers(loop: object, callback: object, **kwargs: object) -> None:
        calls["install_shutdown_handlers"] = True

    monkeypatch.setattr(cli_main, "build_agent", fake_build_agent)
    monkeypatch.setattr(cli_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli_main, "ensure_directories", fake_ensure_directories)
    monkeypatch.setattr(cli_main, "install_shutdown_handlers", fake_install_shutdown_handlers)

    exit_code = main(["start", *_BASE_ARGS])

    assert exit_code == 0
    assert all(calls.values())
