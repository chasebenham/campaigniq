"""Create the CampaignIQ data foundation."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("external_campaign_id", sa.String(100), nullable=False),
        sa.Column("campaign_name", sa.String(180), nullable=False),
        sa.Column("objective", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("target_cpa", sa.Numeric(18, 4)),
        sa.Column("target_roas", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "external_campaign_id", name="uq_campaign_platform_external"),
        sa.CheckConstraint("platform IN ('GOOGLE_ADS', 'META_ADS')", name="ck_campaign_platform"),
        sa.CheckConstraint("objective = 'PURCHASES'", name="ck_campaign_objective"),
        sa.CheckConstraint("status IN ('ACTIVE', 'PAUSED', 'COMPLETED')", name="ck_campaign_status"),
        sa.CheckConstraint("currency = 'USD'", name="ck_campaign_currency"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_campaign_dates"),
        sa.CheckConstraint("target_cpa > 0 AND target_roas > 0", name="ck_campaign_targets"),
    )
    op.create_table(
        "data_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source_platform", sa.String(20)),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("import_status", sa.String(28), nullable=False),
        sa.Column("validation_summary", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.CheckConstraint("source_platform IN ('GOOGLE_ADS', 'META_ADS')", name="ck_import_platform"),
        sa.CheckConstraint("source_type IN ('SYNTHETIC_SEED', 'CSV_UPLOAD')", name="ck_import_source"),
        sa.CheckConstraint(
            "import_status IN ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'REJECTED', 'NO_NEW_ROWS')",
            name="ck_import_status",
        ),
        sa.CheckConstraint(
            "valid_rows >= 0 AND rejected_rows >= 0 AND duplicate_rows >= 0 "
            "AND total_rows = valid_rows + rejected_rows + duplicate_rows",
            name="ck_import_counts",
        ),
    )
    op.create_index("ix_import_time", "data_imports", ["imported_at", "id"])
    op.create_table(
        "daily_campaign_performance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False),
        sa.Column("clicks", sa.BigInteger(), nullable=False),
        sa.Column("spend", sa.Numeric(18, 4), nullable=False),
        sa.Column("attributed_purchases", sa.Numeric(18, 6), nullable=False),
        sa.Column("attributed_purchase_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("conversion_action", sa.String(24), nullable=False),
        sa.Column("attribution_method", sa.String(24), nullable=False),
        sa.Column("attribution_window", sa.String(24), nullable=False),
        sa.Column("date_basis", sa.String(24), nullable=False),
        sa.Column("source_import_id", sa.Integer(), sa.ForeignKey("data_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "report_date", name="uq_performance_campaign_day"),
        sa.CheckConstraint("impressions >= clicks AND clicks >= 0", name="ck_performance_traffic"),
        sa.CheckConstraint(
            "spend >= 0 AND attributed_purchases >= 0 AND attributed_purchase_value >= 0",
            name="ck_performance_values",
        ),
    )
    op.create_index("ix_performance_date_campaign", "daily_campaign_performance", ["report_date", "campaign_id"])
    op.create_index("ix_performance_import", "daily_campaign_performance", ["source_import_id"])
    op.create_table(
        "import_validation_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("data_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(100)),
        sa.Column("error_code", sa.String(50), nullable=False),
        sa.Column("error_message", sa.String(300), nullable=False),
        sa.CheckConstraint("row_number >= 1", name="ck_validation_row_number"),
    )
    op.create_index("ix_validation_import_row", "import_validation_errors", ["import_id", "row_number", "id"])


def downgrade():
    op.drop_table("import_validation_errors")
    op.drop_table("daily_campaign_performance")
    op.drop_table("data_imports")
    op.drop_table("campaigns")
