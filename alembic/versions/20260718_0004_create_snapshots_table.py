"""Create the Snapshots domain table.

Revision ID: 20260718_0004
Revises: 20260715_0003
Create Date: 2026-07-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260718_0004"
down_revision = "20260715_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the UUID-keyed snapshots table with a PostgreSQL JSONB metadata column."""
    op.create_table(
        "snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("original_object_key", sa.String(length=1024), nullable=False),
        sa.Column("thumbnail_object_key", sa.String(length=1024), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_snapshots_device_id"),
        sa.ForeignKeyConstraint(["command_id"], ["commands.id"], name="fk_snapshots_command_id"),
        sa.UniqueConstraint("command_id", name="uq_snapshots_command_id"),
    )
    for column in ("device_id", "command_id", "captured_at"):
        op.create_index(f"ix_snapshots_{column}", "snapshots", [column])


def downgrade() -> None:
    """Remove the snapshots table."""
    for column in ("device_id", "command_id", "captured_at"):
        op.drop_index(f"ix_snapshots_{column}", table_name="snapshots")
    op.drop_table("snapshots")
