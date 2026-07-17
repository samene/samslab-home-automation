"""Create the Device Registry tables.

Revision ID: 20260715_0001
Revises:
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260715_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create UUID-keyed device and capability tables with PostgreSQL JSONB columns."""
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_name", sa.String(length=100), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_version", sa.String(length=100), nullable=True),
        sa.Column("protocol_version", sa.String(length=100), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("device_name", name="uq_devices_device_name"),
    )
    for column in ("device_name", "hostname", "status", "last_seen", "enabled", "deleted_at"):
        op.create_index(f"ix_devices_{column}", "devices", [column])
    op.create_table(
        "device_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("device_id", "capability", name="uq_device_capabilities_device"),
    )
    op.create_index("ix_device_capabilities_device_id", "device_capabilities", ["device_id"])


def downgrade() -> None:
    """Remove Device Registry schema in reverse dependency order."""
    op.drop_index("ix_device_capabilities_device_id", table_name="device_capabilities")
    op.drop_table("device_capabilities")
    for column in ("deleted_at", "enabled", "last_seen", "status", "hostname", "device_name"):
        op.drop_index(f"ix_devices_{column}", table_name="devices")
    op.drop_table("devices")
