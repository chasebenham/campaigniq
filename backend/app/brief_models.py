"""Immutable report versions and separately audited synthesis attempts."""

from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StrategyBrief(Base):
    __tablename__ = "strategy_briefs"
    __table_args__ = (Index("ix_strategy_briefs_updated", "updated_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    reporting_start: Mapped[date]
    reporting_end: Mapped[date]
    current_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StrategyBriefVersion(Base):
    __tablename__ = "strategy_brief_versions"
    __table_args__ = (UniqueConstraint("brief_id", "version", name="uq_strategy_brief_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_id: Mapped[int] = mapped_column(ForeignKey("strategy_briefs.id", ondelete="RESTRICT"))
    version: Mapped[int]
    title: Mapped[str] = mapped_column(String(120))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(24))
    budget_scenario_id: Mapped[int | None] = mapped_column(ForeignKey("budget_scenarios.id", ondelete="RESTRICT"))
    sources: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)
    document: Mapped[dict] = mapped_column(JSON)
    generation_metadata: Mapped[dict | None] = mapped_column(JSON)


PENDING = text("status = 'PENDING'")


class BriefSummaryAttempt(Base):
    __tablename__ = "strategy_brief_summary_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','COMPLETED','FAILED','STALE')", name="ck_brief_summary_status"),
        CheckConstraint("(version_id IS NULL) <> (request_key IS NULL)", name="ck_brief_summary_anchor"),
        Index("ix_brief_summary_created", "created_at"),
        Index("ix_brief_summary_version", "version_id", "id"),
        Index("uq_brief_summary_pending", "version_id", unique=True, postgresql_where=PENDING, sqlite_where=PENDING),
        Index("uq_brief_commentary_request", "request_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_brief_versions.id", ondelete="RESTRICT"))
    request_key: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(24))
    schema_version: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output: Mapped[dict | None] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
