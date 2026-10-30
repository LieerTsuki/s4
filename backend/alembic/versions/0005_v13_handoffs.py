"""v1.3 process handoff indexes, without dataset body columns.

Revision ID: 0005_v13
Revises: 0004_v13
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_v13"
down_revision = "0004_v13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("v13_handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("v13_imports.id"), nullable=False),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("manifest_ref", sa.JSON(), nullable=False),
        sa.UniqueConstraint("import_id", "snapshot_hash"))
    op.create_index("ix_v13_handoffs_import_id", "v13_handoffs", ["import_id"])
    op.create_table("v13_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handoff_id", sa.String(36), sa.ForeignKey("v13_handoffs.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("evidence_ref", sa.JSON(), nullable=False),
        sa.UniqueConstraint("handoff_id", "idempotency_key"))
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='s4_app') THEN
        GRANT SELECT,INSERT ON v13_handoffs,v13_deliveries TO s4_app;
        GRANT UPDATE(status) ON v13_handoffs TO s4_app;
        END IF; END $$""")


def downgrade() -> None:
    raise RuntimeError("Restore an isolated verified backup; never discard sealed v1.3 evidence")
