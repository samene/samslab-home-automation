"""Add workflow/workflow_run references to snapshots.

Revision ID: 20260720_0006
Revises: 20260719_0005
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260720_0006"
down_revision = "20260719_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable, indexed, no-cascade FKs so a snapshot can be traced back to its workflow."""
    op.add_column("snapshots", sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "snapshots", sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_snapshots_workflow_id", "snapshots", "workflows", ["workflow_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_snapshots_workflow_run_id", "snapshots", "workflow_runs", ["workflow_run_id"], ["id"]
    )
    op.create_index("ix_snapshots_workflow_id", "snapshots", ["workflow_id"])
    op.create_index("ix_snapshots_workflow_run_id", "snapshots", ["workflow_run_id"])


def downgrade() -> None:
    """Remove the workflow references."""
    op.drop_index("ix_snapshots_workflow_run_id", table_name="snapshots")
    op.drop_index("ix_snapshots_workflow_id", table_name="snapshots")
    op.drop_constraint("fk_snapshots_workflow_run_id", "snapshots", type_="foreignkey")
    op.drop_constraint("fk_snapshots_workflow_id", "snapshots", type_="foreignkey")
    op.drop_column("snapshots", "workflow_run_id")
    op.drop_column("snapshots", "workflow_id")
