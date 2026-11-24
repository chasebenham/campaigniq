"""Preserve completed versions while deduplicating pending analysis requests."""

from alembic import op
import sqlalchemy as sa

revision = "20261123_0004"
down_revision = "20261123_0003"
branch_labels = None
depends_on = None
IDENTITY = ["finding_id", "evidence_fingerprint", "model", "prompt_version", "schema_version"]


def upgrade():
    op.add_column("ai_analyses", sa.Column("request_id", sa.String(36), nullable=True))
    op.drop_index("uq_ai_analysis_live_evidence", table_name="ai_analyses")
    op.create_index("uq_ai_analysis_pending_evidence", "ai_analyses", IDENTITY, unique=True,
                    postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index("uq_ai_analysis_request", "ai_analyses", ["finding_id", "request_id"], unique=True)


def downgrade():
    duplicates = op.get_bind().execute(sa.text(
        "SELECT 1 FROM ai_analyses WHERE status IN ('PENDING', 'COMPLETED') "
        "GROUP BY finding_id, evidence_fingerprint, model, prompt_version, schema_version "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )).scalar()
    if duplicates:
        raise RuntimeError("Export analysis history before downgrading across regenerated versions.")
    op.drop_index("uq_ai_analysis_request", table_name="ai_analyses")
    op.drop_index("uq_ai_analysis_pending_evidence", table_name="ai_analyses")
    op.create_index("uq_ai_analysis_live_evidence", "ai_analyses", IDENTITY, unique=True,
                    postgresql_where=sa.text("status IN ('PENDING', 'COMPLETED')"))
    op.drop_column("ai_analyses", "request_id")
