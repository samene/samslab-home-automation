"""Create the Notification Framework's delivery-history table.

Revision ID: 20260723_0009
Revises: 20260722_0008
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260723_0009"
down_revision = "20260722_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the notification_logs table — one row per delivery attempt, any provider."""
    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        # No ForeignKey — cross-cutting, unconstrained, same convention as
        # WorkflowStepRun.command_id: this history must survive the workflow
        # it was about being deleted, and is null entirely for a Test
        # Notification, which has no workflow at all.
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_name", sa.String(length=200), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for column in ("provider", "event_type", "workflow_id", "success", "created_at"):
        op.create_index(f"ix_notification_logs_{column}", "notification_logs", [column])


def downgrade() -> None:
    """Drop the notification_logs table."""
    for column in ("provider", "event_type", "workflow_id", "success", "created_at"):
        op.drop_index(f"ix_notification_logs_{column}", table_name="notification_logs")
    op.drop_table("notification_logs")
