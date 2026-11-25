"""Audit commentary drafting before a brief is saved."""

from alembic import op
import sqlalchemy as sa

revision = "20261124_0008"
down_revision = "20261124_0007"
branch_labels = None
depends_on = None

TABLE = "strategy_brief_summary_attempts"


def upgrade():
    op.add_column(TABLE, sa.Column("request_key", sa.String(36)))
    op.alter_column(TABLE, "version_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint("ck_brief_summary_anchor", TABLE, "(version_id IS NULL) <> (request_key IS NULL)")
    op.create_index("uq_brief_commentary_request", TABLE, ["request_key"], unique=True)


def downgrade():
    # Existing report JSON continues to preserve its saved commentary and provenance.
    op.execute(sa.text("DELETE FROM strategy_brief_summary_attempts WHERE version_id IS NULL"))
    op.drop_index("uq_brief_commentary_request", table_name=TABLE)
    op.drop_constraint("ck_brief_summary_anchor", TABLE, type_="check")
    op.alter_column(TABLE, "version_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column(TABLE, "request_key")
