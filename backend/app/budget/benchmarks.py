from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import performance_buckets
from app.budget.schemas import Benchmark, Dates, DEFAULT_ASSUMPTIONS, Defaults
from app.config import Settings
from app.detection import active_run, fingerprint, source_version
from app.detection_config import DetectionConfig
from app.detection_evidence import CampaignFacts, Observation, QualityFlag, finite_nonnegative, inspect_period
from app.detection_models import DetectionFinding
from app.metrics import ratio
from app.models import Campaign, DailyCampaignPerformance
from app.schemas import Filters

REFERENCE_DAYS = 28
REFERENCE_SEARCH_DAYS = 118


class BudgetSettings(Settings):
    budget_min_observed_days: int = Field(14, ge=1, le=28)


class BudgetError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def mature_through(today: date, lag: int) -> date:
    return today - timedelta(days=lag + 1)


def default_reference(db: Session, cutoff: date) -> Dates | None:
    column = DailyCampaignPerformance.report_date
    dates = db.scalars(select(column).where(
        column.between(cutoff - timedelta(days=REFERENCE_SEARCH_DAYS - 1), cutoff)
    ).distinct().order_by(column.desc()))
    # The latest contiguous run of 28 days may start below the cutoff if delivery is delayed.
    end = previous = None
    length = 0
    for day in dates:
        if previous is None or (previous - day).days != 1:
            end, length = day, 0
        length += 1
        if length == REFERENCE_DAYS:
            return Dates(start=day, end=end)
        previous = day
    return None


def defaults(db: Session, settings: BudgetSettings) -> Defaults:
    today, lag = utc_today(), DetectionConfig().maturation_days
    cutoff = mature_through(today, lag)
    return Defaults(
        assumptions=DEFAULT_ASSUMPTIONS, reference=default_reference(db, cutoff),
        planning=Dates(start=today + timedelta(days=1), end=today + timedelta(days=30)),
        mature_through=cutoff, earliest_planning_date=today,
        minimum_observed_days=settings.budget_min_observed_days, maturation_days=lag,
    )


def recent_quality_flags(db: Session, campaign_ids: list[int], reference: Dates):
    run = active_run(db)
    flags = defaultdict(list)
    if run is None or run.source_version != source_version(db):
        return flags
    # Critical reference-window flags are recomputed from source rows. The active run adds advisories.
    rows = db.scalars(select(DetectionFinding).where(
        DetectionFinding.run_id == run.id, DetectionFinding.campaign_id.in_(campaign_ids),
        DetectionFinding.policy_id == "D-06",
    ))
    days = reference.dates()
    for row in rows:
        for item in row.data_quality_flags:
            flag = QualityFlag.model_validate(item)
            relevant = sorted(days.intersection(flag.dates))
            if relevant and not flag.blocking:
                flags[row.campaign_id].append(flag.model_copy(update={"dates": relevant}))
    return flags


def source_snapshot(db: Session, reference: Dates, campaigns: list[Campaign]):
    ids = [campaign.id for campaign in campaigns]
    buckets = performance_buckets(db, Filters(start_date=reference.start, end_date=reference.end), campaign_ids=ids)
    grouped = defaultdict(list)
    for row in buckets:
        grouped[row.campaign_id].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row.date, row.context))
    # Include daily inputs, reporting definitions and campaign lifetimes. Other uploads leave this fingerprint stable.
    digest = fingerprint({
        "reference": reference.model_dump(mode="json"),
        "campaigns": [{
            "id": campaign.id, "name": campaign.campaign_name, "platform": campaign.platform,
            "start": campaign.start_date, "end": campaign.end_date, "currency": campaign.currency,
            "objective": campaign.objective, "rows": [asdict(row) for row in grouped[campaign.id]],
        } for campaign in sorted(campaigns, key=lambda item: item.id)],
    })
    return digest, grouped


def selected_campaigns(db: Session, ids: list[int]) -> list[Campaign]:
    campaigns = list(db.scalars(select(Campaign).where(Campaign.id.in_(ids)).order_by(Campaign.id)))
    if len(campaigns) != len(ids):
        raise BudgetError("CAMPAIGN_NOT_FOUND", "One or more selected campaigns are unavailable.", 404)
    return campaigns


def benchmarks(db: Session, reference: Dates, campaigns: list[Campaign], settings: BudgetSettings) -> tuple[str, list[Benchmark]]:
    lag = DetectionConfig().maturation_days
    if reference.end > mature_through(utc_today(), lag):
        raise BudgetError("IMMATURE_REFERENCE", f"Reference dates must allow {lag} full days for attributed conversions to mature.")
    digest, grouped = source_snapshot(db, reference, campaigns)
    live_flags = recent_quality_flags(db, [campaign.id for campaign in campaigns], reference) if campaigns else {}
    result = []
    for campaign in campaigns:
        rows = grouped[campaign.id]
        facts = CampaignFacts(**{key: getattr(campaign, key) for key in CampaignFacts.__dataclass_fields__})
        source = [Observation(row.date, row.context, row.totals, row.fictional_records > 0) for row in rows]
        period, contexts, flags = inspect_period(facts, source, reference, "reference")
        flags.extend(live_flags.get(campaign.id, []))
        metrics = period.metrics
        blockers = [flag.message for flag in flags if flag.blocking]
        if campaign.currency != "USD" or campaign.objective != "PURCHASES":
            blockers.append("A USD purchase-acquisition campaign is required.")
        if period.observed_days < settings.budget_min_observed_days:
            blockers.append(f"At least {settings.budget_min_observed_days} mature reporting days are required.")
        if not metrics or metrics.spend <= 0 or not metrics.attributed_purchases:
            blockers.append("Positive historical spend and valid attributed purchase credit are required.")
        result.append(Benchmark(
            campaign_id=campaign.id, campaign_name=campaign.campaign_name, platform=campaign.platform,
            eligible=not blockers, blockers=blockers, period=period,
            attribution_contexts=sorted(contexts), flags=flags,
            average_daily_spend=ratio(metrics.spend, period.observed_days) if metrics else None,
            peak_daily_spend=max((observation.totals.spend for observation in source
                                  if finite_nonnegative(observation.totals.spend)), default=None),
        ))
    return digest, result
