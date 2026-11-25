from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.detection_evidence import PeriodEvidence, QualityFlag, Window
from app.domain import Platform, ReportingContext
from app.schemas import PageParams

MODEL_VERSION = "1.0.0"
MAX_CAMPAIGNS = 20
MAX_DAYS = 90
CENT = Decimal("0.01")
HUNDRED = Decimal(100)

PositiveId = Annotated[int, Field(gt=0, le=2**31 - 1)]
Usd = Annotated[Decimal, Field(ge=0, le=100_000_000, decimal_places=2, allow_inf_nan=False)]
Adjustment = Annotated[Decimal, Field(decimal_places=2, allow_inf_nan=False)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Mode = Literal["DOLLARS", "PERCENT"]
Case = Literal["conservative", "base", "optimistic"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Dates(Window):
    model_config = ConfigDict(extra="forbid")

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @model_validator(mode="after")
    def bounds(self):
        if not 1 <= self.days <= MAX_DAYS:
            raise ValueError(f"Choose an inclusive date range of one to {MAX_DAYS} days.")
        return self


class CaseAssumption(StrictModel):
    cpa_change_pct: Adjustment = Field(ge=-90, le=300)
    marginal_cpa_change_pct: Adjustment = Field(ge=0, le=300)
    value_per_purchase_change_pct: Adjustment = Field(ge=-95, le=300)


class Assumptions(StrictModel):
    conservative: CaseAssumption
    base: CaseAssumption
    optimistic: CaseAssumption


DEFAULT_ASSUMPTIONS = Assumptions(
    conservative=CaseAssumption(cpa_change_pct=15, marginal_cpa_change_pct=30, value_per_purchase_change_pct=-5),
    base=CaseAssumption(cpa_change_pct=0, marginal_cpa_change_pct=15, value_per_purchase_change_pct=0),
    optimistic=CaseAssumption(cpa_change_pct=-5, marginal_cpa_change_pct=5, value_per_purchase_change_pct=3),
)


class Defaults(BaseModel):
    assumptions: Assumptions
    reference: Dates | None
    planning: Dates
    mature_through: date
    earliest_planning_date: date
    minimum_observed_days: int
    maturation_days: int
    max_campaigns: int = MAX_CAMPAIGNS


class BenchmarkFilters(PageParams):
    start_date: date | None = None
    end_date: date | None = None
    platform: Platform | None = None
    campaign_id: PositiveId | None = None
    q: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""

    @model_validator(mode="after")
    def paired_dates(self):
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Provide both reference dates.")
        if self.start_date and self.end_date:
            Dates(start=self.start_date, end=self.end_date)
        return self


class Selection(StrictModel):
    campaign_ids: list[PositiveId] = Field(min_length=2, max_length=MAX_CAMPAIGNS)
    reference: Dates
    planning: Dates
    total_budget: Usd

    @model_validator(mode="after")
    def valid_selection(self):
        if len(self.campaign_ids) != len(set(self.campaign_ids)):
            raise ValueError("Each campaign may be selected once.")
        if self.planning.start <= self.reference.end:
            raise ValueError("The planning period must begin after the historical reference period.")
        return self


class Allocation(StrictModel):
    campaign_id: PositiveId
    value: Usd


class Plan(Selection):
    name: Name
    mode: Mode
    allocations: list[Allocation] = Field(min_length=2, max_length=MAX_CAMPAIGNS)
    assumptions: Assumptions
    finding_id: PositiveId | None = None

    @model_validator(mode="after")
    def valid_allocations(self):
        if len(self.allocations) != len(self.campaign_ids) or {row.campaign_id for row in self.allocations} != set(self.campaign_ids):
            raise ValueError("Supply one allocation per selected campaign.")
        expected = self.total_budget if self.mode == "DOLLARS" else HUNDRED
        if sum(row.value for row in self.allocations) != expected:
            raise ValueError(f"Allocations must total {expected:.2f}{'%' if self.mode == 'PERCENT' else ' USD'}.")
        return self


class PresetRequest(Selection):
    method: Literal["historical", "equal", "convert"]
    mode: Mode | None = None
    allocations: list[Allocation] | None = Field(default=None, max_length=MAX_CAMPAIGNS)

    @model_validator(mode="after")
    def valid_conversion(self):
        if self.method == "convert":
            Plan(name="Conversion", mode=self.mode, allocations=self.allocations,
                 assumptions=DEFAULT_ASSUMPTIONS, **self.model_dump(include=set(Selection.model_fields)))
        elif self.mode is not None or self.allocations is not None:
            raise ValueError("Preset allocations take only the selected campaigns and budget dates.")
        return self


class SaveRequest(StrictModel):
    plan: Plan
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CloneRequest(StrictModel):
    name: Name | None = None


class Benchmark(BaseModel):
    campaign_id: int
    campaign_name: str
    platform: Platform
    eligible: bool
    blockers: list[str]
    period: PeriodEvidence
    attribution_contexts: list[ReportingContext]
    flags: list[QualityFlag]
    average_daily_spend: Decimal | None
    peak_daily_spend: Decimal | None


class BudgetWarning(BaseModel):
    code: str
    message: str
    campaign_id: int | None = None
    scenario: Case | None = None
    severity: Literal["notice", "warning"] = "notice"


class AllocationRow(BaseModel):
    campaign_id: int
    dollars: Decimal
    percent: Decimal


class Outcome(BaseModel):
    spend: Decimal
    purchases: Decimal | None
    value: Decimal | None
    cpa: Decimal | None
    roas: Decimal | None


class OutcomeDelta(BaseModel):
    spend: Decimal
    purchases: Decimal | None
    value: Decimal | None
    cpa: Decimal | None
    roas: Decimal | None


class HistoricalAllocation(BaseModel):
    campaign_id: int
    observed_share_pct: Decimal
    normalized_share_pct: Decimal
    planned_share_pct: Decimal
    share_change_pct_points: Decimal
    normalized: Outcome
    planned_spend: Decimal
    spend_change: Decimal
    extrapolation: Literal["none", "modest", "elevated", "substantial"] | None


class CampaignOutcome(BaseModel):
    campaign_id: int
    modeled: Outcome
    delta: OutcomeDelta


class ScenarioOutcome(BaseModel):
    portfolio: Outcome
    delta: OutcomeDelta
    versus_base: OutcomeDelta
    campaigns: list[CampaignOutcome]


class Calculation(BaseModel):
    model_version: str
    evidence_fingerprint: str
    reference_days: int
    planning_days: int
    minimum_observed_days: int
    maturation_days: int
    benchmarks: list[Benchmark]
    allocation: list[HistoricalAllocation]
    observed: Outcome
    normalized: Outcome
    scenarios: dict[Case, ScenarioOutcome]
    warnings: list[BudgetWarning]


class ScenarioSummary(BaseModel):
    id: int
    name: str
    reference: Dates
    planning: Dates
    total_budget: Decimal
    created_at: datetime
    updated_at: datetime
    model_version: str
    evidence_fingerprint: str
    status: Literal["CURRENT", "STALE"]
    cloned_from_id: int | None


class SavedScenario(ScenarioSummary):
    plan: Plan
    result: Calculation
    calculated_at: datetime
