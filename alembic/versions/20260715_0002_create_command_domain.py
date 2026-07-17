"""Create the Command domain tables.

Revision ID: 20260715_0002
Revises: 20260715_0001
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260715_0002"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create UUID-keyed command, result, and event tables with PostgreSQL JSONB columns."""
    op.create_table(
        "commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_type", sa.String(length=150), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("requested_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", sa.String(length=200), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_commands_device_id"),
    )
    for column in (
        "device_id",
        "command_type",
        "status",
        "priority",
        "created_at",
        "expires_at",
        "correlation_id",
        "deleted_at",
    ):
        op.create_index(f"ix_commands_{column}", "commands", [column])
    op.create_index(
        "ix_commands_device_status_created",
        "commands",
        ["device_id", "status", "created_at"],
    )

    op.create_table(
        "command_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["commands.id"],
            name="fk_command_results_command_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("command_id", name="uq_command_results_command_id"),
    )
    op.create_index("ix_command_results_command_id", "command_results", ["command_id"])

    op.create_table(
        "command_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["command_id"], ["commands.id"], name="fk_command_events_command_id", ondelete="CASCADE"
        ),
    )
    for column in ("command_id", "event_type", "timestamp"):
        op.create_index(f"ix_command_events_{column}", "command_events", [column])


def downgrade() -> None:
    """Remove Command domain schema in reverse dependency order."""
    for column in ("command_id", "event_type", "timestamp"):
        op.drop_index(f"ix_command_events_{column}", table_name="command_events")
    op.drop_table("command_events")

    op.drop_index("ix_command_results_command_id", table_name="command_results")
    op.drop_table("command_results")

    op.drop_index("ix_commands_device_status_created", table_name="commands")
    for column in (
        "device_id",
        "command_type",
        "status",
        "priority",
        "created_at",
        "expires_at",
        "correlation_id",
        "deleted_at",
    ):
        op.drop_index(f"ix_commands_{column}", table_name="commands")
    op.drop_table("commands")
