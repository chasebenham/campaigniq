"""Persist Budget Lab plans and immutable calculation snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "20261124_0006"
down_revision = "20261124_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "budget_scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("reference_start", sa.Date(), nullable=False),
        sa.Column("reference_end", sa.Date(), nullable=False),
        sa.Column("planning_start", sa.Date(), nullable=False),
        sa.Column("planning_end", sa.Date(), nullable=False),
        sa.Column("total_budget", sa.Numeric(12, 2), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(24), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("cloned_from_id", sa.Integer(), sa.ForeignKey("budget_scenarios.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("total_budget >= 0", name="ck_budget_scenario_nonnegative"),
    )
    op.create_index("ix_budget_scenario_created", "budget_scenarios", ["created_at", "id"])
    op.create_table(
        "budget_scenario_campaigns",
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("budget_scenarios.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_index("ix_budget_scenario_campaign", "budget_scenario_campaigns", ["campaign_id"])
    op.create_table(
        "budget_scenario_results",
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("budget_scenarios.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model_version", sa.String(24), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("budget_scenario_results")
    op.drop_index("ix_budget_scenario_campaign", table_name="budget_scenario_campaigns")
    op.drop_table("budget_scenario_campaigns")
    op.drop_index("ix_budget_scenario_created", table_name="budget_scenarios")
    op.drop_table("budget_scenarios")
