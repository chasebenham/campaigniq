from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.budget.benchmarks import (
    BudgetError, BudgetSettings, benchmarks, defaults, selected_campaigns, source_snapshot, utc_today,
)
from app.budget.modeling import ZERO, allocation_rows, calculate_plan, checked_eligible, manual_weights
from app.budget.schemas import (
    CENT, AllocationRow, Benchmark, BenchmarkFilters, Calculation, CloneRequest, Dates, Defaults,
    Plan, PresetRequest, SaveRequest, SavedScenario, ScenarioSummary,
)
from app.budget_models import BudgetScenario, BudgetScenarioCampaign, BudgetScenarioResult
from app.db import get_db, lock_performance_writes
from app.detection_config import DetectionConfig
from app.detection_models import DetectionFinding
from app.models import Campaign
from app.schemas import Page, PageParams

router = APIRouter(prefix="/budget-lab", tags=["Budget Lab"])
DB = Annotated[Session, Depends(get_db)]
EntityId = Annotated[int, Path(gt=0, le=2**31 - 1)]


@router.get("/assumptions")
def assumptions(db: DB) -> Defaults:
    return defaults(db, BudgetSettings())


@router.get("/eligible-campaigns")
def campaign_benchmarks(db: DB, filters: Annotated[BenchmarkFilters, Query()]) -> Page[Benchmark]:
    settings = BudgetSettings()
    reference = (Dates(start=filters.start_date, end=filters.end_date) if filters.start_date
                 else defaults(db, settings).reference)
    if reference is None:
        raise BudgetError("NO_REFERENCE", "Choose a mature reference period to review campaigns.")
    query = select(Campaign)
    if filters.platform:
        query = query.where(Campaign.platform == filters.platform)
    if filters.campaign_id:
        query = query.where(Campaign.id == filters.campaign_id)
    if filters.q:
        query = query.where(Campaign.campaign_name.icontains(filters.q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    campaigns = list(db.scalars(query.order_by(Campaign.campaign_name, Campaign.id)
                                 .offset((filters.page - 1) * filters.page_size).limit(filters.page_size)))
    _, rows = benchmarks(db, reference, campaigns, settings)
    return Page(items=rows, page=filters.page, page_size=filters.page_size, total=total)


@router.post("/allocations")
def preset_allocations(body: PresetRequest, db: DB) -> list[AllocationRow]:
    _, rows = benchmarks(db, body.reference, selected_campaigns(db, body.campaign_ids), BudgetSettings())
    eligible = checked_eligible(rows)
    if body.method == "convert":
        return allocation_rows(body.total_budget, manual_weights(body.allocations, eligible), eligible, body.mode)
    weights = {row.campaign_id: (row.average_daily_spend if body.method == "historical" else 1)
               if row.eligible else ZERO for row in rows}
    return allocation_rows(body.total_budget, weights, eligible)


def evaluate(db: Session, plan: Plan, expected: str | None = None) -> Calculation:
    if plan.planning.start < utc_today():
        raise BudgetError("PAST_PLANNING_WINDOW", "Choose a planning period that starts today or later (UTC).")
    if plan.finding_id:
        finding = db.get(DetectionFinding, plan.finding_id)
        if not finding or finding.policy_id not in ("D-01", "D-05") or finding.campaign_id not in plan.campaign_ids:
            raise BudgetError("INVALID_FINDING", "Link a CPA or scaling finding for a selected campaign.")
    settings = BudgetSettings()
    fingerprint, rows = benchmarks(db, plan.reference, selected_campaigns(db, plan.campaign_ids), settings)
    if expected is not None and expected != fingerprint:
        raise BudgetError("STALE_BENCHMARK", "Reference evidence changed. Recalculate before saving.", 409)
    return calculate_plan(plan, rows, fingerprint, settings.budget_min_observed_days, DetectionConfig().maturation_days)


@router.post("/calculate")
def calculate(plan: Plan, db: DB) -> Calculation:
    return evaluate(db, plan)


def get_scenario(db: Session, scenario_id: int) -> BudgetScenario:
    row = db.get(BudgetScenario, scenario_id)
    if row is None:
        raise BudgetError("SCENARIO_NOT_FOUND", "The saved scenario could not be found.", 404)
    return row


def summary(db: Session, row: BudgetScenario) -> ScenarioSummary:
    plan = Plan.model_validate(row.plan)
    current, _ = source_snapshot(db, plan.reference, selected_campaigns(db, plan.campaign_ids))
    return ScenarioSummary(
        id=row.id, name=row.name, reference=plan.reference, planning=plan.planning, total_budget=row.total_budget.quantize(CENT),
        created_at=row.created_at, updated_at=row.updated_at, model_version=row.model_version,
        evidence_fingerprint=row.evidence_fingerprint, status="CURRENT" if current == row.evidence_fingerprint else "STALE",
        cloned_from_id=row.cloned_from_id,
    )


def detail(db: Session, row: BudgetScenario) -> SavedScenario:
    result = db.get(BudgetScenarioResult, row.id)
    return SavedScenario(
        **summary(db, row).model_dump(), plan=Plan.model_validate(row.plan),
        result=Calculation.model_validate(result.result), calculated_at=result.calculated_at,
    )


def record(db: Session, plan: Plan, result: Calculation, original: BudgetScenarioResult | None = None) -> SavedScenario:
    row = BudgetScenario(
        name=plan.name, reference_start=plan.reference.start, reference_end=plan.reference.end,
        planning_start=plan.planning.start, planning_end=plan.planning.end, total_budget=plan.total_budget,
        plan=plan.model_dump(mode="json"), model_version=result.model_version,
        evidence_fingerprint=result.evidence_fingerprint, cloned_from_id=original.scenario_id if original else None,
    )
    db.add(row)
    db.flush()
    db.add_all(BudgetScenarioCampaign(scenario_id=row.id, campaign_id=key) for key in plan.campaign_ids)
    snapshot = BudgetScenarioResult(scenario_id=row.id, model_version=result.model_version, result=result.model_dump(mode="json"))
    if original:
        snapshot.calculated_at = original.calculated_at
    db.add(snapshot)
    db.flush()
    response = detail(db, row)
    db.commit()
    return response


@router.post("/scenarios", status_code=201)
def save_scenario(body: SaveRequest, db: DB) -> SavedScenario:
    lock_performance_writes(db)
    return record(db, body.plan, evaluate(db, body.plan, body.evidence_fingerprint))


@router.get("/scenarios")
def list_scenarios(db: DB, pagination: Annotated[PageParams, Query()]) -> Page[ScenarioSummary]:
    total = db.scalar(select(func.count(BudgetScenario.id)))
    query = (select(BudgetScenario).order_by(BudgetScenario.created_at.desc(), BudgetScenario.id.desc())
             .offset((pagination.page - 1) * pagination.page_size).limit(pagination.page_size))
    rows = list(db.scalars(query))
    return Page(items=[summary(db, row) for row in rows], page=pagination.page,
                page_size=pagination.page_size, total=total)


@router.get("/scenarios/{scenario_id}")
def get_saved_scenario(scenario_id: EntityId, db: DB) -> SavedScenario:
    return detail(db, get_scenario(db, scenario_id))


@router.post("/scenarios/{scenario_id}/clone", status_code=201)
def clone_scenario(scenario_id: EntityId, body: CloneRequest, db: DB) -> SavedScenario:
    row = get_scenario(db, scenario_id)
    source = db.get(BudgetScenarioResult, row.id)
    data = dict(row.plan, name=body.name or f"{row.name[:93].rstrip()} (copy)")
    return record(db, Plan.model_validate(data), Calculation.model_validate(source.result), source)
