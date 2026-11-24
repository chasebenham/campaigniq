from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.detection import (
    EARLIEST_EVALUATION_DATE, RunTooLarge, active_run, execute_run, finding_state, source_version,
)
from app.detection_config import DetectionConfig
from app.detection_evidence import Windows
from app.detection_models import DetectionFinding, DetectionRun, DetectionSuppression
from app.domain import Platform
from app.models import Campaign
from app.schemas import Page, PageParams

router = APIRouter(tags=["Performance detection"])
DB = Annotated[Session, Depends(get_db)]
ID = Annotated[int, Path(gt=0)]
Policy = Literal["D-01", "D-02", "D-03", "D-04", "D-05", "D-06"]
Severity = Literal["HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
Category = Literal["PERFORMANCE_RISK", "OPTIMIZATION_OPPORTUNITY", "DATA_QUALITY"]
State = Literal["CURRENT", "STALE", "HISTORICAL"]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_date: date | None = None

    @model_validator(mode="after")
    def date_range(self):
        if self.evaluation_date and not EARLIEST_EVALUATION_DATE <= self.evaluation_date <= datetime.now(timezone.utc).date():
            raise ValueError("Choose an evaluation date on or before today and within the supported calendar.")
        return self


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    started_at: datetime
    finished_at: datetime
    evaluation_date: date
    windows: Windows
    policy_version: str
    configuration: dict
    input_fingerprint: str | None
    status: Literal["COMPLETED", "FAILED"]
    campaign_count: int
    finding_count: int
    suppression_count: int
    errors: list[dict]
    state: State | None = None
    reused: bool = False


class FindingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    campaign_id: int
    policy_id: Policy
    policy_version: str
    category: Category
    severity: Severity
    summary: str
    classification_reason: str
    current_evidence: dict
    baseline_evidence: dict | None
    campaign_snapshot: dict
    thresholds: dict
    observations: dict
    reporting_context: list[dict]
    evidence_quality: str
    data_quality_flags: list[dict]
    limitations: list[str]
    created_at: datetime
    fingerprint: str
    state: State = "HISTORICAL"


class SuppressionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    campaign_id: int
    campaign_name: str
    platform: Platform
    policy_id: Policy
    category: Literal["INSUFFICIENT_EVIDENCE"] = "INSUFFICIENT_EVIDENCE"
    reason_code: str
    explanation: str
    evidence: dict


class ActiveSummary(BaseModel):
    run: RunView | None
    counts: dict[str, int]


class EvaluationFilters(PageParams):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date must be on or before end date.")
        return self


class RunFilters(EvaluationFilters):
    status: Literal["COMPLETED", "FAILED"] | None = None


class InsightFilters(EvaluationFilters):
    platform: Platform | None = None
    campaign_id: int | None = Field(None, gt=0)
    policy_id: Policy | None = None
    severity: Severity | None = None
    category: Category | None = None
    scope: Literal["current", "history", "all"] = "current"
    sort: Literal["priority", "newest", "spend"] = "priority"


class SuppressionFilters(PageParams):
    platform: Platform | None = None
    campaign_id: int | None = Field(None, gt=0)
    policy_id: Policy | None = None


def require(db: Session, entity, row_id: int):
    record = db.get(entity, row_id)
    if record is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "The requested record could not be found."})
    return record


def run_view(run: DetectionRun, current: DetectionRun | None, version: int, *, reused=False) -> RunView:
    return RunView.model_validate(run).model_copy(update={
        "state": finding_state(run, current, version) if run.status == "COMPLETED" else None, "reused": reused,
    })


def finding_view(finding: DetectionFinding, run: DetectionRun, current: DetectionRun | None, version: int) -> FindingView:
    return FindingView.model_validate(finding).model_copy(update={"state": finding_state(run, current, version)})


@router.post("/detection/runs", status_code=201)
def create_run(db: DB, response: Response, body: RunRequest | None = None) -> RunView:
    try:
        run, reused = execute_run(db, body.evaluation_date if body else None, DetectionConfig())
    except RunTooLarge as error:
        raise HTTPException(422, {"code": "RUN_TOO_LARGE", "message": str(error)}) from error
    view = run_view(run, active_run(db), source_version(db), reused=reused)
    db.commit()
    if reused:
        response.status_code = 200
    return view


@router.get("/detection/runs")
def list_runs(db: DB, filters: Annotated[RunFilters, Query()]) -> Page[RunView]:
    current, version = active_run(db), source_version(db)
    statement = select(DetectionRun)
    if filters.start_date:
        statement = statement.where(DetectionRun.evaluation_date >= filters.start_date)
    if filters.end_date:
        statement = statement.where(DetectionRun.evaluation_date <= filters.end_date)
    if filters.status:
        statement = statement.where(DetectionRun.status == filters.status)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(DetectionRun.id.desc())
                      .offset((filters.page - 1) * filters.page_size).limit(filters.page_size))
    return Page(items=[run_view(run, current, version) for run in rows], page=filters.page,
                page_size=filters.page_size, total=total)


@router.get("/detection/runs/{run_id}")
def get_run(run_id: ID, db: DB) -> RunView:
    return run_view(require(db, DetectionRun, run_id), active_run(db), source_version(db))


@router.get("/detection/runs/{run_id}/suppressions")
def list_suppressions(run_id: ID, db: DB, filters: Annotated[SuppressionFilters, Query()]) -> Page[SuppressionView]:
    require(db, DetectionRun, run_id)
    s = DetectionSuppression
    query = select(s, Campaign.campaign_name, Campaign.platform).join(Campaign).where(s.run_id == run_id)
    if filters.campaign_id is not None:
        query = query.where(s.campaign_id == filters.campaign_id)
    if filters.platform:
        query = query.where(Campaign.platform == filters.platform)
    if filters.policy_id:
        query = query.where(s.policy_id == filters.policy_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = query.order_by(s.id).offset((filters.page - 1) * filters.page_size).limit(filters.page_size)
    items = [SuppressionView(id=row.id, run_id=row.run_id, campaign_id=row.campaign_id, campaign_name=name,
                             platform=platform, policy_id=row.policy_id, reason_code=row.reason_code,
                             explanation=row.explanation, evidence=row.evidence)
             for row, name, platform in db.execute(query)]
    return Page(items=items, page=filters.page, page_size=filters.page_size, total=total)


@router.get("/insights/summary")
def insights_summary(db: DB) -> ActiveSummary:
    current = active_run(db)
    if current is None:
        return ActiveSummary(run=None, counts={})
    rows = db.execute(select(DetectionFinding.category, func.count()).where(DetectionFinding.run_id == current.id)
                      .group_by(DetectionFinding.category))
    return ActiveSummary(run=run_view(current, current, source_version(db)),
                         counts={**dict(rows.all()), "INSUFFICIENT_EVIDENCE": current.suppression_count})


def find_insights(db: Session, filters: InsightFilters) -> Page[FindingView]:
    f, r = DetectionFinding, DetectionRun
    current, version = active_run(db), source_version(db)
    query = select(f, r).join(r).join(Campaign, Campaign.id == f.campaign_id)
    for field, value in (
        (Campaign.platform, filters.platform), (f.campaign_id, filters.campaign_id),
        (f.policy_id, filters.policy_id), (f.severity, filters.severity), (f.category, filters.category),
    ):
        if value is not None:
            query = query.where(field == value)
    if filters.start_date:
        query = query.where(r.evaluation_date >= filters.start_date)
    if filters.end_date:
        query = query.where(r.evaluation_date <= filters.end_date)
    if filters.scope == "current":
        query = query.where(f.run_id == (current.id if current else -1))
    if filters.scope == "history" and current is not None:
        query = query.where(f.run_id != current.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    severity = case({"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFORMATIONAL": 3}, value=f.severity, else_=4)
    sorting = {
        "priority": (severity, f.spend_exposure.desc(), f.magnitude.desc()),
        "spend": (f.spend_exposure.desc(), severity, f.magnitude.desc()),
        "newest": (r.evaluation_date.desc(), r.id.desc()),
    }[filters.sort]
    query = query.order_by(*sorting, f.id.desc()).offset((filters.page - 1) * filters.page_size).limit(filters.page_size)
    return Page(items=[finding_view(finding, run, current, version) for finding, run in db.execute(query)],
                page=filters.page, page_size=filters.page_size, total=total)


@router.get("/insights")
def insights(db: DB, filters: Annotated[InsightFilters, Query()]) -> Page[FindingView]:
    return find_insights(db, filters)


@router.get("/insights/{finding_id}")
def get_insight(finding_id: ID, db: DB) -> FindingView:
    finding = require(db, DetectionFinding, finding_id)
    run = require(db, DetectionRun, finding.run_id)
    return finding_view(finding, run, active_run(db), source_version(db))


@router.get("/campaigns/{campaign_id}/insights")
def campaign_insights(campaign_id: ID, db: DB, filters: Annotated[InsightFilters, Query()]) -> Page[FindingView]:
    require(db, Campaign, campaign_id)
    if filters.campaign_id is not None and filters.campaign_id != campaign_id:
        raise HTTPException(422, {"code": "CAMPAIGN_FILTER_MISMATCH", "message": "Campaign filter must match the path."})
    return find_insights(db, filters.model_copy(update={"campaign_id": campaign_id}))
