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

from pydantic import Field, SecretStr, field_validator, model_validator
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
    # Snapshot capture is independent of streaming (see
    # app/plugins/camera/service.py's capture_snapshot): when no stream is
    # active, it opens its own FrameSource at this (deliberately higher than
    # camera_width/camera_height) resolution, since the whole point of a
    # snapshot is a higher-quality still than the bandwidth-constrained
    # streaming resolution. When a stream *is* active, the snapshot reuses
    # that session's frame source as-is, at whatever resolution it's
    # currently running — these settings don't apply in that case.
    camera_snapshot_width: int = Field(default=1920, gt=0, validation_alias="CAMERA_SNAPSHOT_WIDTH")
    camera_snapshot_height: int = Field(
        default=1080, gt=0, validation_alias="CAMERA_SNAPSHOT_HEIGHT"
    )
    camera_snapshot_thumbnail_width: int = Field(
        default=320, gt=0, validation_alias="CAMERA_SNAPSHOT_THUMBNAIL_WIDTH"
    )
    # AWS credentials the agent uses to upload snapshot images directly to S3
    # (see app/plugins/camera/snapshot_uploader.py). Deliberately separate
    # settings from the cloud server's own aws_* fields (server/app/config/
    # settings.py) — different IAM credentials on each side, least-privilege:
    # the agent only ever needs PutObject on this bucket/prefix, the server
    # only ever needs GetObject/presign + DeleteObject. None for any of the
    # first four disables snapshot uploads entirely (capture_snapshot then
    # raises CameraUnavailableError) rather than the agent failing to start —
    # matching the same "missing optional adapter config is not fatal"
    # pattern already used for MEDIAMTX_JWT_PRIVATE_KEY.
    aws_region: str | None = Field(default=None, validation_alias="AWS_REGION")
    aws_access_key_id: str | None = Field(default=None, validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: SecretStr | None = Field(
        default=None, validation_alias="AWS_SECRET_ACCESS_KEY"
    )
    aws_s3_bucket: str | None = Field(default=None, validation_alias="AWS_S3_BUCKET")
    aws_s3_prefix: str = Field(default="snapshots", validation_alias="AWS_S3_PREFIX")
    # Recording is independent of streaming (see app/plugins/camera/service.py's
    # start_recording/stop_recording): local-only MP4 capture at the highest
    # practical quality, never MediaMTX, uploaded directly to S3 only after
    # the file is finalized. Deliberately higher-quality defaults than
    # camera_width/camera_height/camera_bitrate_kbps, which are tuned for
    # low-latency streaming instead.
    camera_record_width: int = Field(default=1920, gt=0, validation_alias="CAMERA_RECORD_WIDTH")
    camera_record_height: int = Field(default=1080, gt=0, validation_alias="CAMERA_RECORD_HEIGHT")
    camera_record_fps: int = Field(default=30, gt=0, le=120, validation_alias="CAMERA_RECORD_FPS")
    camera_record_bitrate_kbps: int = Field(
        default=8000, gt=0, validation_alias="CAMERA_RECORD_BITRATE_KBPS"
    )
    camera_record_preset: str = Field(default="veryfast", validation_alias="CAMERA_RECORD_PRESET")
    # A safety valve against a forgotten recording silently filling the Pi's
    # local disk (e.g. a stray manual start, or a workflow bug): the pump
    # thread releases the camera hardware once exceeded. The local file
    # itself is left in place, still uploadable by a subsequent
    # camera.record.stop — this never silently discards a recording.
    camera_record_max_duration_seconds: float = Field(
        default=1800.0, gt=0, validation_alias="CAMERA_RECORD_MAX_DURATION_SECONDS"
    )
    # On-sensor HDR (Camera Module 3 / IMX708 only — see
    # app/plugins/camera/sensor_hdr.py), toggled on only around a snapshot's
    # or a recording's own dedicated FrameSource open/close, never around
    # live streaming. Silently a no-op on any other camera (Camera Module 2,
    # a USB webcam), so leaving this enabled is safe everywhere; disable it
    # only if the HDR mode's resolution/framerate tradeoffs aren't wanted.
    camera_hdr_sensor_mode: bool = Field(default=True, validation_alias="CAMERA_HDR_SENSOR_MODE")
    # The pump plugin never controls watering duration — a timer relay wired
    # to this GPIO line owns that entirely. The agent only ever generates one
    # short pulse (pump.trigger) to fire the relay's own timer; see
    # docs/agent/PUMP.md. GPIO17 is a physical-pin-safe default (not one of
    # the boot-strap-sensitive pins like GPIO2/3 (I2C) or GPIO14/15 (UART)),
    # but any deployment can override it.
    pump_gpio_pin: int = Field(default=17, ge=0, le=27, validation_alias="PUMP_GPIO_PIN")
    # Whether energizing the relay's trigger input means driving this line
    # physically HIGH (True, the common case for an active-high opto-isolated
    # relay module) or physically LOW (False, an active-low module). The
    # *safe, idle* level is always the de-energized one — physical LOW when
    # this is True, physical HIGH when it's False — never a raw, polarity-
    # blind "always drive the pin LOW", since that would leave an active-low
    # relay permanently energized at rest. See app/plugins/pump/gpio.py.
    pump_active_high: bool = Field(default=True, validation_alias="PUMP_ACTIVE_HIGH")
    pump_trigger_pulse_ms: int = Field(default=200, gt=0, validation_alias="PUMP_TRIGGER_PULSE_MS")
    # A command-supplied pulse_duration_ms override (pump.trigger's one
    # optional argument) is only honored within these bounds — see
    # PumpTriggerHandler.validate(). Guards against a malformed/malicious
    # override holding the relay's trigger input closed far longer than any
    # real timer relay module needs to latch, or so briefly the relay never
    # reliably triggers at all.
    pump_trigger_pulse_min_ms: int = Field(
        default=50, gt=0, validation_alias="PUMP_TRIGGER_PULSE_MIN_MS"
    )
    pump_trigger_pulse_max_ms: int = Field(
        default=5000, gt=0, validation_alias="PUMP_TRIGGER_PULSE_MAX_MS"
    )
    # Interactive terminal (see app/plugins/terminal/) — an operator escape
    # hatch, off by default so a fresh deployment doesn't expose a shell
    # until someone deliberately opts in. Authorization still happens
    # server-side (RequirePermission("commands.execute")) before the server
    # ever forwards TERMINAL_OPEN; this flag is the agent's own independent
    # kill switch, checked again on every TERMINAL_OPEN.
    terminal_enabled: bool = Field(default=False, validation_alias="TERMINAL_ENABLED")
    terminal_shell: str = Field(default="/bin/bash", validation_alias="TERMINAL_SHELL")
    # A session with no TERMINAL_INPUT for this long is closed automatically
    # — the backstop against a zombie PTY/shell process outliving a browser
    # tab that vanished without ever sending TERMINAL_CLOSE (crash, network
    # loss, laptop closed). Reset by every TERMINAL_INPUT and TERMINAL_RESIZE.
    terminal_session_timeout: float = Field(
        default=300.0, gt=0, validation_alias="TERMINAL_SESSION_TIMEOUT"
    )
    # This agent manages exactly one Raspberry Pi, so more than a handful of
    # concurrent PTYs is never a real use case — bounded mainly to fail a
    # runaway/misbehaving client loudly (TerminalMaxSessionsError) instead of
    # letting shell processes accumulate without limit.
    terminal_max_sessions_per_device: int = Field(
        default=1, ge=1, validation_alias="TERMINAL_MAX_SESSIONS_PER_DEVICE"
    )

    @model_validator(mode="after")
    def validate_pump_pulse_bounds(self) -> AgentSettings:
        """Fail fast on a misconfigured pulse range rather than at the first pump.trigger."""
        if self.pump_trigger_pulse_min_ms > self.pump_trigger_pulse_max_ms:
            raise ValueError("PUMP_TRIGGER_PULSE_MIN_MS must not exceed PUMP_TRIGGER_PULSE_MAX_MS")
        if not (
            self.pump_trigger_pulse_min_ms
            <= self.pump_trigger_pulse_ms
            <= self.pump_trigger_pulse_max_ms
        ):
            raise ValueError(
                "PUMP_TRIGGER_PULSE_MS must be within "
                "[PUMP_TRIGGER_PULSE_MIN_MS, PUMP_TRIGGER_PULSE_MAX_MS]"
            )
        return self

    @field_validator(
        "aws_region", "aws_access_key_id", "aws_secret_access_key", "aws_s3_bucket", mode="before"
    )
    @classmethod
    def parse_aws_optional(cls, value: Any) -> Any:
        """Treat an empty value as "unset" for these optional AWS fields."""
        if value == "":
            return None
        return value

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
