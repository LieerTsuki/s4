"""Append primary verification records per assignment, preserving previous rounds.

Revision ID: 0006_v13
Revises: 0005_v13
"""
from alembic import op

revision = "0006_v13"
down_revision = "0005_v13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A human can independently verify unchanged source content in a new round.
    # Source-content uniqueness must not force overwriting the earlier signature.
    op.drop_constraint("v13_verifications_unit_index_id_content_revision_key",
                       "v13_verifications", type_="unique")
    op.create_unique_constraint("uq_v13_verification_assignment_revision", "v13_verifications",
                                ["assignment_id", "content_revision"])


def downgrade() -> None:
    raise RuntimeError("Restore an isolated verified backup; never discard sealed verification rounds")
