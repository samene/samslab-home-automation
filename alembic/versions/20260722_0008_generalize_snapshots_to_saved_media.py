"""Generalize snapshots into Saved Media (images + videos).

Revision ID: 20260722_0008
Revises: 20260721_0007
Create Date: 2026-07-22
"""

import sqlalchemy as sa

from alembic import op

revision = "20260722_0008"
down_revision = "20260721_0007"
branch_labels = None
depends_on = None

_RENAMED_INDEX_COLUMNS = ("device_id", "command_id", "captured_at", "workflow_id", "workflow_run_id")


def upgrade() -> None:
    """Rename snapshots -> saved_media, add media_type + video-only columns, widen constraints."""
    op.rename_table("snapshots", "saved_media")

    # Rename every index/constraint that still embeds the old table name, so
    # naming stays consistent with every other domain's convention — Postgres
    # does not rename these automatically when a table is renamed.
    op.execute("ALTER TABLE saved_media RENAME CONSTRAINT snapshots_pkey TO saved_media_pkey")
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_snapshots_device_id TO fk_saved_media_device_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_snapshots_command_id TO fk_saved_media_command_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT uq_snapshots_command_id TO uq_saved_media_command_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_snapshots_workflow_id TO fk_saved_media_workflow_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_snapshots_workflow_run_id "
        "TO fk_saved_media_workflow_run_id"
    )
    for column in _RENAMED_INDEX_COLUMNS:
        op.execute(f"ALTER INDEX ix_snapshots_{column} RENAME TO ix_saved_media_{column}")

    # New discriminator (every existing row backfills as IMAGE) + video-only columns.
    op.add_column(
        "saved_media",
        sa.Column("media_type", sa.String(length=20), nullable=False, server_default="IMAGE"),
    )
    op.alter_column("saved_media", "media_type", server_default=None)
    op.create_index("ix_saved_media_media_type", "saved_media", ["media_type"])
    op.add_column("saved_media", sa.Column("duration", sa.Integer(), nullable=True))
    op.add_column("saved_media", sa.Column("fps", sa.Integer(), nullable=True))
    op.add_column("saved_media", sa.Column("bitrate", sa.Integer(), nullable=True))

    # Every existing row is an image with a real thumbnail; only a VIDEO row
    # (no thumbnail generation implemented yet) will ever leave this null.
    op.alter_column("saved_media", "thumbnail_object_key", nullable=True)


def downgrade() -> None:
    """Reverse the generalization back to a snapshot-only table."""
    op.alter_column("saved_media", "thumbnail_object_key", nullable=False)
    op.drop_column("saved_media", "bitrate")
    op.drop_column("saved_media", "fps")
    op.drop_column("saved_media", "duration")
    op.drop_index("ix_saved_media_media_type", table_name="saved_media")
    op.drop_column("saved_media", "media_type")

    for column in _RENAMED_INDEX_COLUMNS:
        op.execute(f"ALTER INDEX ix_saved_media_{column} RENAME TO ix_snapshots_{column}")
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_saved_media_workflow_run_id "
        "TO fk_snapshots_workflow_run_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_saved_media_workflow_id TO fk_snapshots_workflow_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT uq_saved_media_command_id TO uq_snapshots_command_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_saved_media_command_id TO fk_snapshots_command_id"
    )
    op.execute(
        "ALTER TABLE saved_media RENAME CONSTRAINT fk_saved_media_device_id TO fk_snapshots_device_id"
    )
    op.execute("ALTER TABLE saved_media RENAME CONSTRAINT saved_media_pkey TO snapshots_pkey")
    op.rename_table("saved_media", "snapshots")
