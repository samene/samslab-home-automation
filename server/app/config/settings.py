"""Application settings loaded from environment variables and an optional development .env."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Immutable-at-use runtime settings for the cloud server.

    Environment variable names intentionally match the field names so deployment
    configuration remains obvious. Secrets use ``SecretStr`` to reduce accidental
    exposure in representations and logs. The ``jwt_*`` fields are consumed by the
    auth domain; ``s3_*`` and ``victoria_metrics_url`` remain reserved for future
    adapters. The ``mediamtx_*``/``camera_*`` fields are consumed by the Camera
    Application Service to build the browser-facing MediaMTX playback URL and to
    bound how long a REST call waits for a ``camera.stream.*`` command to finish
    (see ``app/application/services/camera_service.py``); they never reach the
    agent, which has its own, separately configured RTSP publish target.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        enable_decoding=False,
        extra="ignore",
    )

    server_name: str = Field(default="Sam's Lab Server", validation_alias="SERVER_NAME")
    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        validation_alias="ENVIRONMENT",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="PORT")
    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    jwt_secret: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_issuer: str = Field(default="samslab", validation_alias="JWT_ISSUER")
    jwt_audience: str = Field(default="samslab-clients", validation_alias="JWT_AUDIENCE")
    jwt_access_token_ttl_seconds: int = Field(
        default=900, ge=1, validation_alias="JWT_ACCESS_TOKEN_TTL_SECONDS"
    )
    jwt_refresh_token_ttl_seconds: int = Field(
        default=1_209_600, ge=1, validation_alias="JWT_REFRESH_TOKEN_TTL_SECONDS"
    )
    jwt_clock_skew_seconds: int = Field(default=30, ge=0, validation_alias="JWT_CLOCK_SKEW_SECONDS")
    s3_endpoint: str | None = Field(default=None, validation_alias="S3_ENDPOINT")
    s3_bucket: str | None = Field(default=None, validation_alias="S3_BUCKET")
    s3_access_key: SecretStr | None = Field(default=None, validation_alias="S3_ACCESS_KEY")
    s3_secret_key: SecretStr | None = Field(default=None, validation_alias="S3_SECRET_KEY")
    victoria_metrics_url: str | None = Field(default=None, validation_alias="VICTORIA_METRICS_URL")
    websocket_path: str = Field(default="/ws", validation_alias="WEBSOCKET_PATH")
    ws_heartbeat_interval_seconds: float = Field(
        default=30.0, gt=0, validation_alias="WS_HEARTBEAT_INTERVAL_SECONDS"
    )
    ws_heartbeat_timeout_seconds: float = Field(
        default=10.0, gt=0, validation_alias="WS_HEARTBEAT_TIMEOUT_SECONDS"
    )
    ws_idle_timeout_seconds: float = Field(
        default=90.0, gt=0, validation_alias="WS_IDLE_TIMEOUT_SECONDS"
    )
    ws_hello_timeout_seconds: float = Field(
        default=10.0, gt=0, validation_alias="WS_HELLO_TIMEOUT_SECONDS"
    )
    ws_outgoing_queue_size: int = Field(
        default=100, ge=1, validation_alias="WS_OUTGOING_QUEUE_SIZE"
    )
    ws_message_ack_timeout_seconds: float = Field(
        default=5.0, gt=0, validation_alias="WS_MESSAGE_ACK_TIMEOUT_SECONDS"
    )
    ws_message_ack_max_retries: int = Field(
        default=3, ge=0, validation_alias="WS_MESSAGE_ACK_MAX_RETRIES"
    )
    dispatcher_poll_interval_seconds: float = Field(
        default=1.0, gt=0, validation_alias="DISPATCHER_POLL_INTERVAL_SECONDS"
    )
    dispatcher_discovery_batch_size: int = Field(
        default=100, ge=1, validation_alias="DISPATCHER_DISCOVERY_BATCH_SIZE"
    )
    dispatcher_ack_timeout_seconds: float = Field(
        default=10.0, gt=0, validation_alias="DISPATCHER_ACK_TIMEOUT_SECONDS"
    )
    dispatcher_execution_timeout_seconds: float = Field(
        default=300.0, gt=0, validation_alias="DISPATCHER_EXECUTION_TIMEOUT_SECONDS"
    )
    dispatcher_max_retries: int = Field(default=4, ge=0, validation_alias="DISPATCHER_MAX_RETRIES")
    dispatcher_retry_backoff_base_seconds: float = Field(
        default=1.0, gt=0, validation_alias="DISPATCHER_RETRY_BACKOFF_BASE_SECONDS"
    )
    dispatcher_retry_backoff_max_seconds: float = Field(
        default=30.0, gt=0, validation_alias="DISPATCHER_RETRY_BACKOFF_MAX_SECONDS"
    )
    dispatcher_sweep_interval_seconds: float = Field(
        default=1.0, gt=0, validation_alias="DISPATCHER_SWEEP_INTERVAL_SECONDS"
    )
    allow_origins: tuple[str, ...] = Field(default=(), validation_alias="ALLOW_ORIGINS")
    mediamtx_host: str = Field(default="127.0.0.1", validation_alias="MEDIAMTX_HOST")
    mediamtx_playback_scheme: Literal["http", "https"] = Field(
        default="http", validation_alias="MEDIAMTX_PLAYBACK_SCHEME"
    )
    # None omits the port from the constructed playback_url entirely — for
    # when a reverse proxy/load balancer terminates TLS on the scheme's
    # implicit default port (443 for https, 80 for http) and forwards to
    # MediaMTX's real port internally; the browser never needs to see that
    # internal port at all.
    mediamtx_playback_port: int | None = Field(
        default=8889, ge=1, le=65535, validation_alias="MEDIAMTX_PLAYBACK_PORT"
    )
    # MediaMTX JWT-based read auth (see app/core/mediamtx_jwt.py): a browser
    # can't carry Basic Auth credentials in a URL anymore (Chrome removed
    # support for user:pass@host in 2022), and MediaMTX's HLS/WebRTC reads
    # accept neither query-parameter credentials nor a custom Authorization
    # header from a plain <iframe>/<video> load — so the frontend instead
    # drives playback through hls.js, which *can* set a header per-request.
    # This key is a distinct RSA keypair from the app's own HS256 JWT_SECRET;
    # MEDIAMTX_JWT_PRIVATE_KEY is the base64 encoding of a PKCS8 PEM private
    # key (base64 to survive .env's bash-sourcing unscathed — see lib.sh).
    # None disables MediaMTX JWT auth entirely (playback_token stays null).
    mediamtx_jwt_private_key: SecretStr | None = Field(
        default=None, validation_alias="MEDIAMTX_JWT_PRIVATE_KEY"
    )
    mediamtx_jwt_key_id: str = Field(default="mediamtx-1", validation_alias="MEDIAMTX_JWT_KEY_ID")
    # Must match mediamtx.yml's authJWTIssuer/authJWTAudience if those are
    # set there; leave both unset (on both sides) to skip the check entirely.
    mediamtx_jwt_issuer: str | None = Field(default=None, validation_alias="MEDIAMTX_JWT_ISSUER")
    mediamtx_jwt_audience: str | None = Field(
        default=None, validation_alias="MEDIAMTX_JWT_AUDIENCE"
    )
    # Short-lived on purpose: minted fresh on every camera/status poll, never
    # persisted, only ever used to open a read (browser) session a few
    # seconds after issuance.
    mediamtx_jwt_ttl_seconds: float = Field(
        default=60.0, gt=0, validation_alias="MEDIAMTX_JWT_TTL_SECONDS"
    )
    # Much longer than the read TTL above: this one authorizes the agent's
    # RTSP *publish* connection (delivered in a camera.stream.start command's
    # payload, see CameraApplicationService.start_stream), which can stay
    # open for hours and has no token-refresh logic on the agent side — it
    # must outlive the longest stream session an operator is expected to run.
    mediamtx_jwt_publish_ttl_seconds: float = Field(
        default=86400.0, gt=0, validation_alias="MEDIAMTX_JWT_PUBLISH_TTL_SECONDS"
    )
    camera_stream_name: str = Field(default="camera", validation_alias="CAMERA_STREAM_NAME")
    camera_command_timeout_seconds: float = Field(
        default=15.0, gt=0, validation_alias="CAMERA_COMMAND_TIMEOUT_SECONDS"
    )
    camera_command_poll_interval_seconds: float = Field(
        default=0.25, gt=0, validation_alias="CAMERA_COMMAND_POLL_INTERVAL_SECONDS"
    )
    camera_snapshot_command_timeout_seconds: float = Field(
        default=60.0, gt=0, validation_alias="CAMERA_SNAPSHOT_COMMAND_TIMEOUT_SECONDS"
    )
    # Independent of the agent's own AWS_* settings (agent/app/config/settings.py):
    # least-privilege in mind, this side only ever needs GetObject/presign +
    # DeleteObject, never PutObject — see app/core/s3_client.py.
    aws_region: str | None = Field(default=None, validation_alias="AWS_REGION")
    aws_access_key_id: str | None = Field(default=None, validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: SecretStr | None = Field(
        default=None, validation_alias="AWS_SECRET_ACCESS_KEY"
    )
    aws_s3_bucket: str | None = Field(default=None, validation_alias="AWS_S3_BUCKET")
    aws_presigned_url_ttl_seconds: float = Field(
        default=300.0, gt=0, validation_alias="AWS_PRESIGNED_URL_TTL_SECONDS"
    )
    workflow_command_timeout_seconds: float = Field(
        default=60.0, gt=0, validation_alias="WORKFLOW_COMMAND_TIMEOUT_SECONDS"
    )
    workflow_command_poll_interval_seconds: float = Field(
        default=0.25, gt=0, validation_alias="WORKFLOW_COMMAND_POLL_INTERVAL_SECONDS"
    )
    workflow_run_shutdown_wait_seconds: float = Field(
        default=30.0, gt=0, validation_alias="WORKFLOW_RUN_SHUTDOWN_WAIT_SECONDS"
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize a logging level while rejecting empty values."""
        normalized = value.upper().strip()
        if not normalized:
            raise ValueError("LOG_LEVEL must not be empty")
        return normalized

    @field_validator("websocket_path")
    @classmethod
    def validate_websocket_path(cls, value: str) -> str:
        """Keep the future WebSocket route path well-formed without creating it."""
        if not value.startswith("/"):
            raise ValueError("WEBSOCKET_PATH must start with '/'")
        return value

    @field_validator("mediamtx_playback_port", mode="before")
    @classmethod
    def parse_mediamtx_playback_port(cls, value: Any) -> Any:
        """Treat an empty MEDIAMTX_PLAYBACK_PORT as "omit the port from the URL"."""
        if value == "":
            return None
        return value

    @field_validator(
        "mediamtx_jwt_private_key", "mediamtx_jwt_issuer", "mediamtx_jwt_audience", mode="before"
    )
    @classmethod
    def parse_mediamtx_jwt_optional(cls, value: Any) -> Any:
        """Treat an empty value as "unset" for these optional MediaMTX JWT fields."""
        if value == "":
            return None
        return value

    @field_validator(
        "aws_region", "aws_access_key_id", "aws_secret_access_key", "aws_s3_bucket", mode="before"
    )
    @classmethod
    def parse_aws_optional(cls, value: Any) -> Any:
        """Treat an empty value as "unset" for these optional AWS fields."""
        if value == "":
            return None
        return value

    @field_validator("allow_origins", mode="before")
    @classmethod
    def parse_allow_origins(cls, value: Any) -> tuple[str, ...]:
        """Accept a comma-separated environment value or a settings-compatible sequence."""
        if value in (None, ""):
            return ()
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        if isinstance(value, (list, tuple)):
            return tuple(str(origin).strip() for origin in value if str(origin).strip())
        raise ValueError("ALLOW_ORIGINS must be a comma-separated string or sequence")
