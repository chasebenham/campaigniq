from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PENDING_ATTEMPT = text("status = 'PENDING'")


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'COMPLETED', 'STALE', 'FAILED')", name="ck_ai_analysis_status"),
        Index("ix_ai_analysis_finding_created", "finding_id", "created_at", "id"),
        Index("ix_ai_analysis_created", "created_at"),
        Index("uq_ai_analysis_pending_evidence", "finding_id", "evidence_fingerprint", "model",
              "prompt_version", "schema_version", unique=True,
              postgresql_where=PENDING_ATTEMPT, sqlite_where=PENDING_ATTEMPT),
        Index("uq_ai_analysis_request", "finding_id", "request_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("detection_findings.id", ondelete="RESTRICT"))
    request_id: Mapped[str | None] = mapped_column(String(36))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64))
    evidence_snapshot: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(24))
    schema_version: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    structured_output: Mapped[dict | None] = mapped_column(JSON)
    provider_usage: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(300))
