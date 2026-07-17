"""Agent settings loaded from environment variables and an optional development .env.

Field names and validation follow the same convention as the cloud server's own
``Settings`` (``server/app/config/settings.py``): ``validation_alias`` pins the
environment variable name, secrets use ``SecretStr``, and normalization lives in
``field_validator``s rather than being repeated at every call site.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Immutable-at-use runtime settings for the Raspberry Pi agent.

    Pydantic Settings resolves fields in priority order: explicit constructor
    kwargs, then environment variables, then ``.env``, then the field default.
    That ordering is what makes ``load_settings(overrides)`` "command-line
    overrides beat environment beats .env" work with no extra plumbing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        enable_decoding=False,
        extra="ignore",
    )

    server_url: str = Field(validation_alias="SERVER_URL")
    device_name: str = Field(validation_alias="DEVICE_NAME")
    device_display_name: str | None = Field(default=None, validation_alias="DEVICE_DISPLAY_NAME")
    device_description: str | None = Field(default=None, validation_alias="DEVICE_DESCRIPTION")
    # Replaces the old static DEVICE_TOKEN (a pre-minted, 15-minute-TTL JWT
    # that, once expired with no live connection, left the agent with no way
    # to reconnect — see docs/architecture/SECURITY.md). DEVICE_PRIVATE_KEY
    # never expires and is never transmitted: on every connection attempt the
    # agent signs a fresh, short-lived assertion with it and exchanges that
    # for a real access token via AUTH_TOKEN_URL (see
    # app/connection/token_provider.py). Base64-encoded PKCS8 PEM, matching
    # MEDIAMTX_JWT_PRIVATE_KEY's encoding server-side, both for the same
    # reason: surviving a bash-sourced .env unscathed.
    device_client_id: str = Field(validation_alias="DEVICE_CLIENT_ID")
    device_private_key: SecretStr = Field(validation_alias="DEVICE_PRIVATE_KEY")
    # The server's POST /auth/device/token URL. Explicit rather than derived
    # from server_url: in the hybrid deployment this is reached through Caddy
    # at a /api-prefixed path (e.g. https://samslab.site/api/auth/device/token),
    # while server_url is a ws(s):// URL to a *different* path (/ws) — the two
    # aren't related by a simple scheme swap.
    auth_token_url: str = Field(validation_alias="AUTH_TOKEN_URL")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    heartbeat_interval: float = Field(default=30.0, gt=0, validation_alias="HEARTBEAT_INTERVAL")
    reconnect_interval: float = Field(default=5.0, gt=0, validation_alias="RECONNECT_INTERVAL")
    protocol_version: int = Field(default=1, ge=1, validation_alias="PROTOCOL_VERSION")
    local_data_directory: Path = Field(
        default=Path("/var/lib/samslab-agent"), validation_alias="LOCAL_DATA_DIRECTORY"
    )
    cache_directory: Path = Field(
        default=Path("/var/cache/samslab-agent"), validation_alias="CACHE_DIRECTORY"
    )
    tmp_directory: Path = Field(
        default=Path("/tmp/samslab-agent"), validation_alias="TMP_DIRECTORY"
    )
    debug: bool = Field(
        default=False,
        validation_alias="DEBUG",
        description="Include a stack trace on a failed command's result; off by default in production.",
    )
    mediamtx_host: str = Field(default="127.0.0.1", validation_alias="MEDIAMTX_HOST")
    mediamtx_port: int = Field(default=8554, ge=1, le=65535, validation_alias="MEDIAMTX_PORT")
    mediamtx_playback_scheme: Literal["http", "https"] = Field(
        default="http", validation_alias="MEDIAMTX_PLAYBACK_SCHEME"
    )
    # Not in the original spec's field list, but required to build a *playback*
    # URL (see camera.stream.start's result) — MediaMTX serves browser playback
    # on a different port than the one the agent publishes RTSP to. None omits
    # the port from the URL entirely — for a reverse proxy/load balancer that
    # terminates the scheme's implicit default port (443/80) and forwards to
    # MediaMTX's real port internally.
    mediamtx_playback_port: int | None = Field(
        default=8889, ge=1, le=65535, validation_alias="MEDIAMTX_PLAYBACK_PORT"
    )
    mediamtx_username: str = Field(default="", validation_alias="MEDIAMTX_USERNAME")
    mediamtx_password: SecretStr = Field(
        default=SecretStr(""), validation_alias="MEDIAMTX_PASSWORD"
    )
    stream_name: str = Field(default="camera", validation_alias="STREAM_NAME")
    camera_device_index: int = Field(default=0, ge=0, validation_alias="CAMERA_DEVICE_INDEX")
    camera_width: int = Field(default=1280, gt=0, validation_alias="CAMERA_WIDTH")
    camera_height: int = Field(default=720, gt=0, validation_alias="CAMERA_HEIGHT")
    camera_fps: int = Field(default=30, gt=0, le=120, validation_alias="CAMERA_FPS")
    # No safe universal default exists — 1500 is a reasonable starting point
    # for 720p over a modest WAN link; tune to what the actual path between
    # agent and MediaMTX sustains (see docs/agent/CAMERA.md).
    camera_bitrate_kbps: int = Field(default=1500, gt=0, validation_alias="CAMERA_BITRATE_KBPS")
    # "ultrafast" (libx264's fastest, least efficient preset) was the
    # original default; Pi 5 has enough headroom to afford "veryfast" for
    # meaningfully better quality at the same bitrate, at a small CPU/latency
    # cost. Slower presets (e.g. "faster", "fast") trade further encode time
    # for further efficiency if a Pi 5's CPU allows it.
    camera_preset: str = Field(default="veryfast", validation_alias="CAMERA_PRESET")

    @field_validator("mediamtx_playback_port", mode="before")
    @classmethod
    def parse_mediamtx_playback_port(cls, value: Any) -> Any:
        """Treat an empty MEDIAMTX_PLAYBACK_PORT as "omit the port from the URL"."""
        if value == "":
            return None
        return value

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        """Reject anything that isn't a WebSocket URL before it reaches the connection layer."""
        if not (value.startswith("ws://") or value.startswith("wss://")):
            raise ValueError("SERVER_URL must start with 'ws://' or 'wss://'")
        return value

    @field_validator("device_name")
    @classmethod
    def validate_device_name(cls, value: str) -> str:
        """Reject an empty device name; it identifies this agent to the server."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("DEVICE_NAME must not be empty")
        return normalized

    @field_validator("device_client_id")
    @classmethod
    def validate_device_client_id(cls, value: str) -> str:
        """Reject an empty client_id; every assertion and token request carries it."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("DEVICE_CLIENT_ID must not be empty")
        return normalized

    @field_validator("device_private_key")
    @classmethod
    def validate_device_private_key(cls, value: SecretStr) -> SecretStr:
        """Reject an empty key; every assertion would otherwise be unsigned."""
        if not value.get_secret_value().strip():
            raise ValueError("DEVICE_PRIVATE_KEY must not be empty")
        return value

    @field_validator("auth_token_url")
    @classmethod
    def validate_auth_token_url(cls, value: str) -> str:
        """Reject anything that isn't an HTTP(S) URL before it reaches the token provider."""
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("AUTH_TOKEN_URL must start with 'http://' or 'https://'")
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize a logging level while rejecting empty values."""
        normalized = value.upper().strip()
        if not normalized:
            raise ValueError("LOG_LEVEL must not be empty")
        return normalized


def load_settings(overrides: Mapping[str, Any] | None = None) -> AgentSettings:
    """Build settings from environment/.env, then apply explicit CLI overrides.

    ``overrides`` should only contain keys the caller actually set (e.g. a CLI
    flag the user passed) — a present key with value ``None`` would shadow a
    real environment value with ``None`` and fail validation.
    """
    return AgentSettings(**(overrides or {}))
