from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DetectionRun(Base):
    __tablename__ = "detection_runs"
    __table_args__ = (
        CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="ck_detection_run_status"),
        CheckConstraint("campaign_count >= 0 AND finding_count >= 0 AND suppression_count >= 0",
                        name="ck_detection_run_counts"),
        Index("ix_detection_run_status_id", "status", "id"),
        Index("ix_detection_run_evaluation", "evaluation_date", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluation_date: Mapped[date]
    windows: Mapped[dict] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(24))
    configuration: Mapped[dict] = mapped_column(JSON)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    source_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    campaign_count: Mapped[int]
    finding_count: Mapped[int]
    suppression_count: Mapped[int]
    errors: Mapped[list] = mapped_column(JSON)


class DetectionFinding(Base):
    __tablename__ = "detection_findings"
    __table_args__ = (
        UniqueConstraint("run_id", "campaign_id", "policy_id", name="uq_detection_run_campaign_policy"),
        CheckConstraint("policy_id IN ('D-01', 'D-02', 'D-03', 'D-04', 'D-05', 'D-06')",
                        name="ck_detection_finding_policy"),
        CheckConstraint("category IN ('PERFORMANCE_RISK', 'OPTIMIZATION_OPPORTUNITY', 'DATA_QUALITY')",
                        name="ck_detection_finding_category"),
        CheckConstraint("severity IN ('HIGH', 'MEDIUM', 'LOW', 'INFORMATIONAL')",
                        name="ck_detection_finding_severity"),
        Index("ix_detection_finding_campaign_run", "campaign_id", "run_id"),
        Index("ix_detection_finding_run_severity", "run_id", "severity"),
        Index("ix_detection_finding_fingerprint", "fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("detection_runs.id", ondelete="RESTRICT"))
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"))
    policy_id: Mapped[str] = mapped_column(String(4))
    policy_version: Mapped[str] = mapped_column(String(24))
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(String(350))
    classification_reason: Mapped[str] = mapped_column(String(350))
    current_evidence: Mapped[dict] = mapped_column(JSON)
    baseline_evidence: Mapped[dict | None] = mapped_column(JSON)
    campaign_snapshot: Mapped[dict] = mapped_column(JSON)
    thresholds: Mapped[dict] = mapped_column(JSON)
    observations: Mapped[dict] = mapped_column(JSON)
    reporting_context: Mapped[list] = mapped_column(JSON)
    evidence_quality: Mapped[str] = mapped_column(String(20))
    data_quality_flags: Mapped[list] = mapped_column(JSON)
    limitations: Mapped[list] = mapped_column(JSON)
    spend_exposure: Mapped[Decimal] = mapped_column(Numeric(30, 4))
    magnitude: Mapped[Decimal] = mapped_column(Numeric())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fingerprint: Mapped[str] = mapped_column(String(64))


class DetectionSuppression(Base):
    __tablename__ = "detection_suppressions"
    __table_args__ = (
        UniqueConstraint("run_id", "campaign_id", "policy_id", name="uq_suppression_run_campaign_policy"),
        Index("ix_detection_suppression_run_reason", "run_id", "reason_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("detection_runs.id", ondelete="RESTRICT"))
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"))
    policy_id: Mapped[str] = mapped_column(String(4))
    reason_code: Mapped[str] = mapped_column(String(48))
    explanation: Mapped[str] = mapped_column(String(350))
    evidence: Mapped[dict] = mapped_column(JSON)
