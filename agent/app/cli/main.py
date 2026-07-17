"""``samslab-agent``: start / version / health / config / validate-config.

Argparse rather than a third-party CLI framework — five flat subcommands
don't need one, and it keeps the agent's own dependency footprint small.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from app.config.settings import AgentSettings, load_settings
from app.health.results import HealthState
from app.lifecycle.factory import build_agent, build_health_service
from app.logging.configure import configure_logging
from app.system.directories import ensure_directories
from app.system.signals import install_shutdown_handlers
from app.utils.version import AGENT_VERSION

#: Health-check exit codes follow a Nagios-style severity ordering.
_HEALTH_EXIT_CODES: dict[HealthState, int] = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.UNHEALTHY: 2,
}


def _add_config_override_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the flags that can override any environment/.env-sourced setting."""
    parser.add_argument("--server-url", dest="server_url")
    parser.add_argument("--device-name", dest="device_name")
    parser.add_argument("--device-display-name", dest="device_display_name")
    parser.add_argument("--device-description", dest="device_description")
    parser.add_argument("--device-client-id", dest="device_client_id")
    parser.add_argument("--device-private-key", dest="device_private_key")
    parser.add_argument("--auth-token-url", dest="auth_token_url")
    parser.add_argument("--log-level", dest="log_level")
    parser.add_argument("--heartbeat-interval", dest="heartbeat_interval", type=float)
    parser.add_argument("--reconnect-interval", dest="reconnect_interval", type=float)
    parser.add_argument("--protocol-version", dest="protocol_version", type=int)


def _cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Collect only the override flags the user actually passed.

    Keys match each field's ``validation_alias`` (the environment variable
    name), not the Python field name — ``AgentSettings`` doesn't set
    ``populate_by_name``, so the alias is the only accepted constructor key.
    """
    mapping = {
        "SERVER_URL": args.server_url,
        "DEVICE_NAME": args.device_name,
        "DEVICE_DISPLAY_NAME": args.device_display_name,
        "DEVICE_DESCRIPTION": args.device_description,
        "DEVICE_CLIENT_ID": args.device_client_id,
        "DEVICE_PRIVATE_KEY": args.device_private_key,
        "AUTH_TOKEN_URL": args.auth_token_url,
        "LOG_LEVEL": args.log_level,
        "HEARTBEAT_INTERVAL": args.heartbeat_interval,
        "RECONNECT_INTERVAL": args.reconnect_interval,
        "PROTOCOL_VERSION": args.protocol_version,
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _load_settings_from_args(args: argparse.Namespace) -> AgentSettings:
    return load_settings(_cli_overrides(args))


def build_parser() -> argparse.ArgumentParser:
    """Build the ``samslab-agent`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="samslab-agent", description="Sam's Lab Raspberry Pi edge agent"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Run the agent")
    _add_config_override_arguments(start_parser)

    subparsers.add_parser("version", help="Print the agent version")

    health_parser = subparsers.add_parser("health", help="Print a one-shot local health report")
    _add_config_override_arguments(health_parser)

    config_parser = subparsers.add_parser("config", help="Print the resolved configuration")
    _add_config_override_arguments(config_parser)

    validate_parser = subparsers.add_parser(
        "validate-config", help="Validate configuration and exit"
    )
    _add_config_override_arguments(validate_parser)

    return parser


def _cmd_start(args: argparse.Namespace) -> int:
    settings = _load_settings_from_args(args)
    configure_logging(settings)
    ensure_directories(
        [settings.local_data_directory, settings.cache_directory, settings.tmp_directory]
    )
    agent = build_agent(settings)

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        install_shutdown_handlers(loop, agent.request_stop)
        await agent.run()

    asyncio.run(_run())
    return 0


def _cmd_version(_: argparse.Namespace) -> int:
    print(AGENT_VERSION)
    return 0


def _cmd_health(args: argparse.Namespace) -> int:
    settings = _load_settings_from_args(args)
    report = build_health_service(settings).check()
    print(
        json.dumps(
            {
                "state": report.state.value,
                "checks": [
                    {"name": check.name, "state": check.state.value, "detail": check.detail}
                    for check in report.checks
                ],
            },
            indent=2,
        )
    )
    return _HEALTH_EXIT_CODES[report.state]


def _cmd_config(args: argparse.Namespace) -> int:
    settings = _load_settings_from_args(args)
    print(json.dumps(settings.model_dump(mode="json"), indent=2, default=str))
    return 0


def _cmd_validate_config(args: argparse.Namespace) -> int:
    try:
        _load_settings_from_args(args)
    except Exception as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return 1
    print("Configuration is valid.")
    return 0


_COMMANDS = {
    "start": _cmd_start,
    "version": _cmd_version,
    "health": _cmd_health,
    "config": _cmd_config,
    "validate-config": _cmd_validate_config,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``samslab-agent`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
