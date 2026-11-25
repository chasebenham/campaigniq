"""Immutable planning scenarios and their recorded calculation snapshots."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BudgetScenario(Base):
    __tablename__ = "budget_scenarios"
    __table_args__ = (
        CheckConstraint("total_budget >= 0", name="ck_budget_scenario_nonnegative"),
        Index("ix_budget_scenario_created", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    reference_start: Mapped[date]
    reference_end: Mapped[date]
    planning_start: Mapped[date]
    planning_end: Mapped[date]
    total_budget: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    plan: Mapped[dict] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(24))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64))
    cloned_from_id: Mapped[int | None] = mapped_column(ForeignKey("budget_scenarios.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetScenarioCampaign(Base):
    __tablename__ = "budget_scenario_campaigns"
    __table_args__ = (Index("ix_budget_scenario_campaign", "campaign_id"),)

    scenario_id: Mapped[int] = mapped_column(ForeignKey("budget_scenarios.id", ondelete="CASCADE"), primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="RESTRICT"), primary_key=True)


class BudgetScenarioResult(Base):
    __tablename__ = "budget_scenario_results"

    scenario_id: Mapped[int] = mapped_column(ForeignKey("budget_scenarios.id", ondelete="CASCADE"), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(24))
    result: Mapped[dict] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
