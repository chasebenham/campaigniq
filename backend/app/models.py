from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
    Index, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("platform", "external_campaign_id", name="uq_campaign_platform_external"),
        CheckConstraint("platform IN ('GOOGLE_ADS', 'META_ADS')", name="ck_campaign_platform"),
        CheckConstraint("objective = 'PURCHASES'", name="ck_campaign_objective"),
        CheckConstraint("status IN ('ACTIVE', 'PAUSED', 'COMPLETED')", name="ck_campaign_status"),
        CheckConstraint("currency = 'USD'", name="ck_campaign_currency"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_campaign_dates"),
        CheckConstraint("target_cpa > 0 AND target_roas > 0", name="ck_campaign_targets"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    external_campaign_id: Mapped[str] = mapped_column(String(100))
    campaign_name: Mapped[str] = mapped_column(String(180))
    objective: Mapped[str] = mapped_column(String(20), default="PURCHASES")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    target_cpa: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    target_roas: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    performance: Mapped[list["DailyCampaignPerformance"]] = relationship(back_populates="campaign")


class DataImport(Base):
    __tablename__ = "data_imports"
    __table_args__ = (
        CheckConstraint(
            "source_platform IN ('GOOGLE_ADS', 'META_ADS')", name="ck_import_platform"
        ),
        CheckConstraint("source_type IN ('SYNTHETIC_SEED', 'CSV_UPLOAD')", name="ck_import_source"),
        CheckConstraint(
            "import_status IN ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'REJECTED', 'NO_NEW_ROWS')",
            name="ck_import_status",
        ),
        CheckConstraint(
            "valid_rows >= 0 AND rejected_rows >= 0 AND duplicate_rows >= 0 "
            "AND total_rows = valid_rows + rejected_rows + duplicate_rows",
            name="ck_import_counts",
        ),
        Index("ix_import_time", "imported_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source_platform: Mapped[str | None] = mapped_column(String(20))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_rows: Mapped[int]
    valid_rows: Mapped[int]
    rejected_rows: Mapped[int]
    duplicate_rows: Mapped[int]
    import_status: Mapped[str] = mapped_column(String(28))
    validation_summary: Mapped[dict] = mapped_column(JSON)
    source_type: Mapped[str] = mapped_column(String(20))
    errors: Mapped[list["ImportValidationError"]] = relationship(
        back_populates="data_import", cascade="all, delete-orphan"
    )


class DailyCampaignPerformance(Base):
    __tablename__ = "daily_campaign_performance"
    __table_args__ = (
        UniqueConstraint("campaign_id", "report_date", name="uq_performance_campaign_day"),
        Index("ix_performance_date_campaign", "report_date", "campaign_id"),
        Index("ix_performance_import", "source_import_id"),
        CheckConstraint("impressions >= clicks AND clicks >= 0", name="ck_performance_traffic"),
        CheckConstraint(
            "spend >= 0 AND attributed_purchases >= 0 AND attributed_purchase_value >= 0",
            name="ck_performance_values",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"))
    report_date: Mapped[date] = mapped_column(Date)
    impressions: Mapped[int] = mapped_column(BigInteger)
    clicks: Mapped[int] = mapped_column(BigInteger)
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    attributed_purchases: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    attributed_purchase_value: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    conversion_action: Mapped[str] = mapped_column(String(24))
    attribution_method: Mapped[str] = mapped_column(String(24))
    attribution_window: Mapped[str] = mapped_column(String(24))
    date_basis: Mapped[str] = mapped_column(String(24))
    source_import_id: Mapped[int] = mapped_column(ForeignKey("data_imports.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    campaign: Mapped[Campaign] = relationship(back_populates="performance")


class ImportValidationError(Base):
    __tablename__ = "import_validation_errors"
    __table_args__ = (
        Index("ix_validation_import_row", "import_id", "row_number", "id"),
        CheckConstraint("row_number >= 1", name="ck_validation_row_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("data_imports.id", ondelete="CASCADE"))
    row_number: Mapped[int]
    field_name: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str] = mapped_column(String(50))
    error_message: Mapped[str] = mapped_column(String(300))
    data_import: Mapped[DataImport] = relationship(back_populates="errors")
