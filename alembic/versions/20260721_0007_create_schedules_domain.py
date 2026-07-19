"""Create the Schedules domain tables.

Revision ID: 20260721_0007
Revises: 20260720_0006
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260721_0007"
down_revision = "20260720_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create UUID-keyed schedule and schedule-execution tables."""
    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("schedule_type", sa.String(length=20), nullable=False),
        sa.Column("cron_expression", sa.String(length=120), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # No cascade to workflows.id — cross-domain, same convention as
        # snapshots.workflow_id: workflows are only ever soft-deleted, so
        # this never dangles.
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], name="fk_schedules_workflow_id"),
    )
    for column in ("workflow_id", "name", "enabled", "next_run_at", "deleted_at"):
        op.create_index(f"ix_schedules_{column}", "schedules", [column])

    op.create_table(
        "schedule_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            name="fk_schedule_executions_schedule_id",
            ondelete="CASCADE",
        ),
        # Both no cascade, cross-domain — same convention as schedules.workflow_id above.
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"], name="fk_schedule_executions_workflow_id"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_schedule_executions_workflow_run_id",
        ),
    )
    for column in ("schedule_id", "workflow_id", "workflow_run_id", "triggered_at", "status"):
        op.create_index(f"ix_schedule_executions_{column}", "schedule_executions", [column])


def downgrade() -> None:
    """Remove Schedules domain schema in reverse dependency order."""
    for column in ("schedule_id", "workflow_id", "workflow_run_id", "triggered_at", "status"):
        op.drop_index(f"ix_schedule_executions_{column}", table_name="schedule_executions")
    op.drop_table("schedule_executions")

    for column in ("workflow_id", "name", "enabled", "next_run_at", "deleted_at"):
        op.drop_index(f"ix_schedules_{column}", table_name="schedules")
    op.drop_table("schedules")
