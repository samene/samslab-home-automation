"""Create the Workflows domain tables.

Revision ID: 20260719_0005
Revises: 20260718_0004
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260719_0005"
down_revision = "20260718_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create UUID-keyed workflow, step, run, and step-run tables."""
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=20), nullable=True),
        sa.Column("last_run_duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("name", "enabled", "deleted_at"):
        op.create_index(f"ix_workflows_{column}", "workflows", [column])

    op.create_table(
        "workflow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=20), nullable=False),
        sa.Column("command_type", sa.String(length=150), nullable=True),
        sa.Column("sleep_seconds", sa.Integer(), nullable=True),
        sa.Column("group_mode", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"], name="fk_workflow_steps_workflow_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_step_id"],
            ["workflow_steps.id"],
            name="fk_workflow_steps_parent_step_id",
            ondelete="CASCADE",
        ),
    )
    for column in ("workflow_id", "parent_step_id"):
        op.create_index(f"ix_workflow_steps_{column}", "workflow_steps", [column])

    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"], name="fk_workflow_runs_workflow_id", ondelete="CASCADE"
        ),
    )
    for column in ("workflow_id", "status", "started_at"):
        op.create_index(f"ix_workflow_runs_{column}", "workflow_runs", [column])

    op.create_table(
        "workflow_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_workflow_step_runs_workflow_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id"],
            ["workflow_steps.id"],
            name="fk_workflow_step_runs_workflow_step_id",
            ondelete="CASCADE",
        ),
        # No cascade to commands.id — cross-domain, same convention as snapshots.command_id.
        sa.ForeignKeyConstraint(
            ["command_id"], ["commands.id"], name="fk_workflow_step_runs_command_id"
        ),
    )
    for column in ("workflow_run_id", "workflow_step_id", "status", "command_id"):
        op.create_index(f"ix_workflow_step_runs_{column}", "workflow_step_runs", [column])


def downgrade() -> None:
    """Remove Workflows domain schema in reverse dependency order."""
    for column in ("workflow_run_id", "workflow_step_id", "status", "command_id"):
        op.drop_index(f"ix_workflow_step_runs_{column}", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")

    for column in ("workflow_id", "status", "started_at"):
        op.drop_index(f"ix_workflow_runs_{column}", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    for column in ("workflow_id", "parent_step_id"):
        op.drop_index(f"ix_workflow_steps_{column}", table_name="workflow_steps")
    op.drop_table("workflow_steps")

    for column in ("name", "enabled", "deleted_at"):
        op.drop_index(f"ix_workflows_{column}", table_name="workflows")
    op.drop_table("workflows")
