"""Add executive strategy brief snapshots and synthesis attempts."""

from alembic import op
import sqlalchemy as sa

revision = "20261124_0007"
down_revision = "20261124_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "strategy_briefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("reporting_start", sa.Date(), nullable=False),
        sa.Column("reporting_end", sa.Date(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_strategy_briefs_updated", "strategy_briefs", ["updated_at", "id"])
    op.create_table(
        "strategy_brief_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brief_id", sa.Integer(), sa.ForeignKey("strategy_briefs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(24), nullable=False),
        sa.Column("budget_scenario_id", sa.Integer(), sa.ForeignKey("budget_scenarios.id", ondelete="RESTRICT")),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("narrative", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("generation_metadata", sa.JSON()),
        sa.UniqueConstraint("brief_id", "version", name="uq_strategy_brief_version"),
    )
    op.create_table(
        "strategy_brief_summary_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("strategy_brief_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(24), nullable=False),
        sa.Column("schema_version", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("output", sa.JSON()),
        sa.Column("usage", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint("status IN ('PENDING','COMPLETED','FAILED','STALE')", name="ck_brief_summary_status"),
    )
    op.create_index("ix_brief_summary_created", "strategy_brief_summary_attempts", ["created_at"])
    op.create_index("ix_brief_summary_version", "strategy_brief_summary_attempts", ["version_id", "id"])
    op.create_index("uq_brief_summary_pending", "strategy_brief_summary_attempts", ["version_id"], unique=True,
                    postgresql_where=sa.text("status = 'PENDING'"), sqlite_where=sa.text("status = 'PENDING'"))


def downgrade():
    op.drop_table("strategy_brief_summary_attempts")
    op.drop_table("strategy_brief_versions")
    op.drop_table("strategy_briefs")
