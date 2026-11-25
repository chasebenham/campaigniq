"""Assemble an auditable report from existing measurements and immutable source artifacts."""

from dataclasses import asdict, replace
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import analytics
from app.ai_contract import AnalysisOutput, DetailedAnalysisOutput, LegacyAnalysisOutput, build_snapshot, cited_paths, references
from app.ai_models import AIAnalysis
from app.briefs.schemas import AnalysisOption, Defaults, FindingOption, Options, OptionsParams, Period, Sources
from app.budget.api import detail as budget_detail
from app.budget.benchmarks import BudgetError, mature_through, utc_today
from app.budget_models import BudgetScenario
from app.detection import MAX_CAMPAIGNS, active_run, finding_state, fingerprint, source_version
from app.detection_api import finding_view
from app.detection_config import DetectionConfig
from app.detection_evidence import finite_nonnegative
from app.detection_models import DetectionFinding, DetectionRun
from app.metrics import Totals
from app.models import Campaign, DailyCampaignPerformance
from app.schemas import Filters, Page

ACCEPTED_OUTPUT = TypeAdapter(AnalysisOutput | DetailedAnalysisOutput | LegacyAnalysisOutput)


def error(status: int, code: str, message: str):
    return HTTPException(status, {"code": code, "message": message})


def defaults(db: Session) -> Defaults:
    cutoff = mature_through(utc_today(), DetectionConfig().maturation_days)
    run = active_run(db)
    if run and finding_state(run, run, source_version(db)) == "CURRENT":
        period = Period.model_validate(run.windows["current"])
        return Defaults(period=period, suggested_run_id=run.id)
    last = db.scalar(select(func.max(DailyCampaignPerformance.report_date)).where(
        DailyCampaignPerformance.report_date <= cutoff))
    if last is None:
        return Defaults(period=None, suggested_run_id=None)
    return Defaults(period=Period(start=last - timedelta(days=6), end=last), suggested_run_id=None)


def accepted_analysis(record: AIAnalysis | None, finding: DetectionFinding) -> dict | None:
    if not record or record.finding_id != finding.id or record.status != "COMPLETED" or not record.structured_output:
        return None
    snapshot = record.evidence_snapshot
    if snapshot.get("finding_id") != finding.id or fingerprint(snapshot) != record.evidence_fingerprint:
        return None
    try:
        output = ACCEPTED_OUTPUT.validate_python(record.structured_output).model_dump(mode="json")
        catalog = references(snapshot)
        paths = cited_paths(output)
    except (ValidationError, KeyError, TypeError):
        return None
    if not paths or any(path not in catalog for path in paths):
        return None
    return {
        "id": record.id, "model": record.model, "schema_version": record.schema_version,
        "prompt_version": record.prompt_version, "references": {path: catalog[path] for path in paths},
        "evidence_fingerprint": record.evidence_fingerprint,
        "historical": record.evidence_fingerprint != fingerprint(build_snapshot(finding)),
        "output": output,
    }


def finding_options(db: Session, params: OptionsParams) -> Options:
    f, r = DetectionFinding, DetectionRun
    run, version = active_run(db), source_version(db)
    query = select(f, r).join(r, f.run_id == r.id).where(
        r.status == "COMPLETED", f.current_evidence["start"].as_string() >= params.start.isoformat(),
        f.current_evidence["end"].as_string() <= params.end.isoformat(),
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    current_id = run.id if run and finding_state(run, run, version) == "CURRENT" else None
    priority = case({"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFORMATIONAL": 3}, value=f.severity, else_=4)
    ordering = (case((r.id == current_id, 0), else_=1), r.evaluation_date.desc(), r.id.desc(),
                priority, f.spend_exposure.desc(), f.id)
    recommended = set()
    suggested_run_id = None
    if current_id is not None:
        recommended = {row[0].id for row in db.execute(query.where(r.id == current_id).order_by(*ordering).limit(3))}
        if recommended:
            suggested_run_id = current_id
    query = query.order_by(*ordering).offset((params.page - 1) * params.page_size).limit(params.page_size)
    items = []
    for finding, parent in db.execute(query):
        view = finding_view(finding, parent, run, version)
        matches = db.scalars(select(AIAnalysis).where(
            AIAnalysis.finding_id == finding.id, AIAnalysis.status == "COMPLETED",
        ).order_by(AIAnalysis.id.desc()).limit(12))
        analyses = []
        for analysis in matches:
            if item := accepted_analysis(analysis, finding):
                analyses.append(AnalysisOption(id=analysis.id, model=analysis.model, created_at=analysis.created_at,
                                               historical=item["historical"] or view.state != "CURRENT"))
        items.append(FindingOption(finding=view, analyses=analyses, suggested=finding.id in recommended))
    return Options(suggested_run_id=suggested_run_id,
                   findings=Page(items=items, page=params.page, page_size=params.page_size, total=total))


def performance(db: Session, period: Period) -> tuple[dict, str, list[str]]:
    campaigns = list(db.scalars(select(Campaign).order_by(Campaign.id).limit(MAX_CAMPAIGNS + 1)))
    if len(campaigns) > MAX_CAMPAIGNS:
        raise error(422, "REPORT_TOO_LARGE", f"Strategy Briefs supports workspaces of up to {MAX_CAMPAIGNS:,} campaigns.")
    buckets = analytics.performance_buckets(db, Filters(start_date=period.start, end_date=period.end),
                                            campaign_ids=[campaign.id for campaign in campaigns])
    observed = {row.date for row in buckets}
    by_campaign: dict[int, set] = {}
    for row in buckets:
        by_campaign.setdefault(row.campaign_id, set()).add(row.date)
    expected = missing = outside = 0
    scope = []
    for row in campaigns:
        start, end = max(row.start_date, period.start), min(row.end_date or period.end, period.end)
        reported = by_campaign.get(row.id, set())
        if start <= end or reported:
            scope.append((row.id, row.platform, row.start_date, row.end_date))
        expected += max(0, (end - start).days + 1)
        matched = sum(start <= day <= end for day in reported)
        missing += max(0, (end - start).days + 1) - matched
        outside += len(reported) - matched
    ordered = sorted(buckets, key=lambda row: (row.date, row.campaign_id, row.context))
    raw_digest = fingerprint({"scope": scope, "buckets": [asdict(row) for row in ordered]})
    warnings = []
    if missing:
        warnings.append(f"{missing:,} of {expected:,} expected campaign-day reports are missing. Totals reflect observed records.")
    if outside:
        warnings.append(f"{outside:,} campaign-day records fall outside their recorded campaign dates. Review coverage before drawing conclusions.")
    if period.end > mature_through(utc_today(), DetectionConfig().maturation_days):
        warnings.append("The reporting period includes recent days whose attributed conversions may still mature.")
    if not buckets:
        warnings.append("No campaign observations are available for the selected dates.")

    invalid_traffic = any(
        not all(finite_nonnegative(value) for value in (row.totals.impressions, row.totals.clicks, row.totals.spend))
        or row.totals.clicks > row.totals.impressions for row in buckets
    )
    invalid_conversion = any(
        not all(finite_nonnegative(value) for value in (row.totals.attributed_purchases, row.totals.attributed_purchase_value))
        or (row.totals.attributed_purchases == 0 and row.totals.attributed_purchase_value > 0)
        for row in buckets
    )
    if invalid_traffic:
        warnings.append("Invalid traffic or spend was found. Portfolio and platform KPI tables are withheld.")
        buckets_for_metrics = [replace(row, totals=Totals()) for row in buckets]
    elif invalid_conversion:
        warnings.append("Invalid conversion values were found. Purchase credit, value, CPA and ROAS are withheld.")
        buckets_for_metrics = [replace(row, totals=Totals(row.totals.impressions, row.totals.clicks, row.totals.spend))
                               for row in buckets]
    else:
        buckets_for_metrics = buckets
    report = analytics.summarize(buckets_for_metrics)
    platforms = analytics.platforms(buckets_for_metrics)
    for item in [report, *platforms]:
        if invalid_traffic:
            item.metrics = None
            item.conversion_status = "unavailable"
        elif invalid_conversion and item.metrics:
            item.conversion_status = "unavailable"
            for field in ("attributed_purchases", "attributed_purchase_value", "cpa", "roas", "purchase_cvr", "attributed_aov"):
                setattr(item.metrics, field, None)
    if report.conversion_status == "incompatible":
        warnings.append("Blended conversion metrics are withheld because attribution definitions differ.")
    elif report.conversion_status == "unavailable" and not (invalid_conversion or invalid_traffic):
        warnings.append("Conversion metrics are withheld where reporting definitions are unknown or unsupported.")
    if report.platform_attributed_overlap:
        warnings.append("Google Ads and Meta can both claim credit for the same purchase. Combined figures are platform-attributed and may overlap.")
    # Trends are spend only. Gaps remain absent and each group represents actual observed dates.
    weekly: dict[date, dict[str, Any]] = {}
    if not invalid_traffic:
        for row in analytics.trends(buckets_for_metrics).items:
            start = period.start + timedelta(days=((row.date - period.start).days // 7) * 7)
            group = weekly.setdefault(start, {"start": start.isoformat(), "end": min(start + timedelta(days=6), period.end).isoformat(),
                                              "days": 0, "spend": 0})
            group["days"] += 1
            group["spend"] += row.metrics.spend
    data = {
        "portfolio": report.model_dump(mode="json"), "platforms": [row.model_dump(mode="json") for row in platforms],
        "expected_days": expected, "missing_days": missing, "calendar_days": (period.end - period.start).days + 1,
        "days_with_data": len(observed), "trend": [dict(row, spend=str(row["spend"])) for row in weekly.values()],
    }
    return data, raw_digest, warnings


def collect(db: Session, sources: Sources, *, allow_historical: bool) -> dict:
    report, raw_digest, warnings = performance(db, sources.period)
    active, version = active_run(db), source_version(db)
    items = []
    for selection in sources.findings:
        finding = db.get(DetectionFinding, selection.finding_id)
        parent = db.get(DetectionRun, finding.run_id) if finding else None
        if not finding or not parent or parent.status != "COMPLETED":
            raise error(422, "INVALID_FINDING", "A selected detection finding is unavailable.")
        view = finding_view(finding, parent, active, version)
        current = view.current_evidence
        if not sources.period.start.isoformat() <= current["start"] <= current["end"] <= sources.period.end.isoformat():
            raise error(422, "FINDING_OUTSIDE_PERIOD", f"Finding #{finding.id} must have its complete evaluation window within the report period.")
        if view.state != "CURRENT":
            warnings.append(f"Finding #{finding.id} is {view.state.lower()}. It preserves the original detection evidence.")
        chosen = None
        if selection.analysis_id:
            chosen = accepted_analysis(db.get(AIAnalysis, selection.analysis_id), finding)
            if not chosen:
                raise error(422, "INVALID_ANALYSIS", "Choose a completed, evidence-validated analysis for its own finding.")
            if chosen["historical"] or view.state != "CURRENT":
                chosen["historical"] = True
                warnings.append(f"AI analysis #{chosen['id']} is historical or stale. Review it in its original evidence context.")
        items.append({"finding": view.model_dump(mode="json"), "analysis": chosen})

    overlapping = set()
    for index, item in enumerate(items):
        a = item["finding"]
        for other in items[index + 1:]:
            b = other["finding"]
            if a["campaign_id"] == b["campaign_id"] and max(
                a["current_evidence"]["start"], b["current_evidence"]["start"]
            ) <= min(a["current_evidence"]["end"], b["current_evidence"]["end"]):
                overlapping.update((a["id"], b["id"]))
    if overlapping:
        ids = ", ".join(f"#{key}" for key in sorted(overlapping))
        warnings.append(f"Findings {ids} share a campaign and reporting dates. Their financial effects cannot be added together.")
    report_contexts = {fingerprint(context) for context in report["portfolio"]["attribution_contexts"]}
    finding_contexts = {fingerprint(context) for item in items for context in item["finding"]["reporting_context"]}
    if finding_contexts and len(report_contexts | finding_contexts) > 1:
        warnings.append("Selected findings and report totals include differing measurement definitions. Review each finding in its original context.")

    budget = None
    if sources.budget_id:
        row = db.get(BudgetScenario, sources.budget_id)
        if row is None:
            raise error(422, "INVALID_BUDGET", "Choose an available saved Budget Lab scenario.")
        try:
            budget = budget_detail(db, row).model_dump(mode="json")
        except BudgetError as exc:
            raise error(exc.status, exc.code, str(exc)) from exc
        if budget["status"] == "STALE":
            warnings.append(f"Budget scenario #{row.id} has stale reference evidence. Its saved inputs and modeled results are preserved.")
        period = sources.period
        if budget["reference"] != period.model_dump(mode="json"):
            warnings.append("The attached budget scenario uses its own reference dates. Its normalized history is separate from this report’s observed totals.")

    if not allow_historical and (any(item["finding"]["state"] != "CURRENT" or (
        item["analysis"] and item["analysis"]["historical"]) for item in items) or (budget and budget["status"] == "STALE")):
        raise error(409, "HISTORICAL_SOURCE", "Review the historical or stale selections and explicitly acknowledge them before including them.")
    return {
        "raw_metrics_fingerprint": raw_digest, "performance": report, "findings": items,
        "budget": budget, "warnings": warnings, "period": sources.period.model_dump(mode="json"),
    }


def evidence_fingerprint(evidence: dict) -> str:
    # Capture source availability and state, not clock-dependent maturity notices or report prose.
    return fingerprint({key: value for key, value in evidence.items() if key != "warnings"})
