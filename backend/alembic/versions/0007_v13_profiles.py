"""Independent v1.3 profiles; never migrate or reinterpret legacy approvals."""
import sqlalchemy as sa

from alembic import op

revision = "0007_v13_profiles"
down_revision = "0006_v13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("v13_profile_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset", sa.String(20), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("manual_version", sa.String(100), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("canonical_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_ref", sa.JSON(), nullable=False),
        sa.Column("manual_ref", sa.JSON(), nullable=False),
        sa.Column("vocabulary_ref", sa.JSON(), nullable=False),
        sa.Column("approval_ref", sa.JSON()),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("contributor_person_ids", sa.JSON(), nullable=False),
        sa.Column("approver_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("dataset", "version"))
    op.create_table("v13_profile_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("profile_revision_id", sa.String(36), sa.ForeignKey("v13_profile_revisions.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("record_ref", sa.JSON(), nullable=False),
        sa.UniqueConstraint("profile_revision_id", "revision"))
    op.create_index("ix_v13_profile_events_profile_revision_id", "v13_profile_events", ["profile_revision_id"])
    op.add_column("v13_batches", sa.Column("profile_revision_id", sa.String(36), sa.ForeignKey("v13_profile_revisions.id")))
    op.add_column("v13_batches", sa.Column("profile_hash", sa.String(64)))
    for field in ("profile_snapshot_ref", "profile_approval_ref", "manual_ref", "vocabulary_ref"):
        op.add_column("v13_batches", sa.Column(field, sa.JSON()))
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='s4_app') THEN GRANT SELECT,INSERT,UPDATE ON v13_profile_revisions TO s4_app; GRANT SELECT,INSERT ON v13_profile_events TO s4_app; END IF; END $$;")


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; do not discard independent approvals or frozen batch rules")
