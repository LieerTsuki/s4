"""Allow exposure events before an annotation batch exists."""
from alembic import op
import sqlalchemy as sa

revision = "0002_s4"
down_revision = "0001_s4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("exposures", "batch_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    # An upload exposure cannot be discarded merely to roll back a schema version.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM exposures WHERE batch_id IS NULL) THEN RAISE EXCEPTION 'upload exposures require schema 0002'; END IF; END $$")
    op.alter_column("exposures", "batch_id", existing_type=sa.String(36), nullable=False)
