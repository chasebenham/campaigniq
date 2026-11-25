from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.domain import CONTEXT_FIELDS, CONTEXT_OPTIONS, Platform, SourceType, ReportingContext
from app.metrics import Totals, calculate, sum_totals
from app.models import Campaign, DailyCampaignPerformance, DataImport
from app.schemas import (
    Attribution, CampaignFilters, CampaignMetadata, CampaignReport, Filters,
    Page, PlatformReport, Report, TrendPoint, TrendReport,
)


@dataclass(frozen=True)
class PerformanceBucket:
    date: date
    campaign_id: int
    platform: Platform
    context: ReportingContext
    totals: Totals
    records: int
    fictional_records: int
    latest_import_at: datetime


def campaign_conditions(filters: Filters):
    conditions = []
    if filters.platform is not None:
        conditions.append(Campaign.platform == filters.platform)
    if filters.campaign_id is not None:
        conditions.append(Campaign.id == filters.campaign_id)
    return conditions


def performance_buckets(session: Session, filters: Filters, *, campaign_ids: list[int] | None = None) -> list[PerformanceBucket]:
    p = DailyCampaignPerformance
    context_columns = [getattr(p, field) for field in CONTEXT_FIELDS]
    metric_columns = [getattr(p, field) for field in Totals.__dataclass_fields__]
    dimensions = (p.report_date, p.campaign_id, Campaign.platform, *context_columns)
    query = (
        select(
            *dimensions,
            *(func.sum(column) for column in metric_columns),
            func.count(p.id),
            func.sum(case((DataImport.source_type == SourceType.SYNTHETIC_SEED, 1), else_=0)),
            func.max(DataImport.imported_at),
        )
        .join(Campaign, Campaign.id == p.campaign_id)
        .join(DataImport, DataImport.id == p.source_import_id)
        .where(*campaign_conditions(filters))
        .group_by(*dimensions)
        .order_by(p.report_date)
    )
    if filters.start_date:
        query = query.where(p.report_date >= filters.start_date)
    if campaign_ids is not None:
        query = query.where(p.campaign_id.in_(campaign_ids))
    if filters.end_date:
        query = query.where(p.report_date <= filters.end_date)
    if isinstance(filters, CampaignFilters) and filters.status:
        query = query.where(Campaign.status == filters.status)

    return [
        PerformanceBucket(report_date, campaign_id, Platform(platform), ReportingContext(action, method, window, basis),
                          Totals(int(impressions), int(clicks), spend, purchases, purchase_value),
                          records, fictional_records, latest_import)
        for report_date, campaign_id, platform, action, method, window, basis,
            impressions, clicks, spend, purchases, purchase_value, records, fictional_records, latest_import
        in session.execute(query)
    ]


def summarize(buckets: list[PerformanceBucket]) -> Report:
    contexts = sorted({bucket.context for bucket in buckets})
    recognized = all(
        getattr(context, field) in choices and getattr(context, field) != "UNKNOWN"
        for context in contexts for field, choices in CONTEXT_OPTIONS.items()
    )
    if not buckets:
        status = "empty"
    elif len(contexts) > 1:
        status = "incompatible"
    elif not recognized:
        status = "unavailable"
    else:
        status = "available"

    observed_dates = {bucket.date for bucket in buckets}
    return Report(
        metrics=calculate(sum_totals(bucket.totals for bucket in buckets), conversions_available=status == "available")
        if buckets else None,
        first_date=min(observed_dates, default=None),
        last_date=max(observed_dates, default=None),
        latest_import_at=max((bucket.latest_import_at for bucket in buckets), default=None),
        record_count=sum(bucket.records for bucket in buckets),
        fictional_record_count=sum(bucket.fictional_records for bucket in buckets),
        observed_days=len(observed_dates),
        attribution_contexts=[Attribution(**asdict(context)) for context in contexts],
        conversion_status=status,
        platform_attributed_overlap=len({bucket.platform for bucket in buckets}) > 1,
    )


def trends(buckets: list[PerformanceBucket]) -> TrendReport:
    summary = summarize(buckets)
    daily = defaultdict(list)
    for bucket in buckets:
        daily[bucket.date].append(bucket.totals)
    return TrendReport(
        first_date=summary.first_date,
        last_date=summary.last_date,
        items=[
            TrendPoint(date=day, metrics=calculate(sum_totals(totals),
                       conversions_available=summary.conversion_status == "available"))
            for day, totals in sorted(daily.items())
        ],
    )


def platforms(buckets: list[PerformanceBucket]) -> list[PlatformReport]:
    grouped = defaultdict(list)
    for bucket in buckets:
        grouped[bucket.platform].append(bucket)
    return [
        PlatformReport(platform=platform, **summarize(rows).model_dump())
        for platform, rows in sorted(grouped.items())
    ]


def campaign_report(campaign: Campaign, buckets: list[PerformanceBucket], filters: Filters) -> CampaignReport:
    report = summarize(buckets)
    missing_days = None
    if report.first_date and report.last_date:
        first = max(campaign.start_date, filters.start_date or report.first_date)
        last = min(campaign.end_date or date.max, filters.end_date or report.last_date)
        missing_days = max(0, (last - first).days + 1 - report.observed_days)
    cpa = report.metrics.cpa if report.metrics else None
    roas = report.metrics.roas if report.metrics else None
    return CampaignReport(
        **CampaignMetadata.model_validate(campaign).model_dump(),
        report=report,
        missing_days=missing_days,
        cpa_target_status=("met" if cpa <= campaign.target_cpa else "missed")
        if cpa is not None and campaign.target_cpa is not None else None,
        roas_target_status=("met" if roas >= campaign.target_roas else "missed")
        if roas is not None and campaign.target_roas is not None else None,
    )


def campaign_reports(session: Session, filters: CampaignFilters) -> Page[CampaignReport]:
    conditions = campaign_conditions(filters)
    if filters.status:
        conditions.append(Campaign.status == filters.status)
    grouped = defaultdict(list)
    for bucket in performance_buckets(session, filters):
        grouped[bucket.campaign_id].append(bucket)
    campaign_query = select(Campaign).where(*conditions).order_by(Campaign.id)
    if filters.start_date or filters.end_date:
        if not grouped:
            return Page(items=[], page=filters.page, page_size=filters.page_size, total=0)
        # Use a subquery to avoid one bind parameter per filtered campaign.
        p = DailyCampaignPerformance
        active = select(p.campaign_id)
        if filters.start_date:
            active = active.where(p.report_date >= filters.start_date)
        if filters.end_date:
            active = active.where(p.report_date <= filters.end_date)
        campaign_query = campaign_query.where(Campaign.id.in_(active))
    rows = [
        campaign_report(campaign, grouped[campaign.id], filters)
        for campaign in session.scalars(campaign_query)
    ]

    def sort_value(row: CampaignReport):
        if filters.sort in {"campaign_name", "platform", "status"}:
            return getattr(row, filters.sort).casefold()
        if filters.sort in {"target_cpa", "target_roas"}:
            return getattr(row, filters.sort)
        if filters.sort in {"first_date", "last_date"}:
            return getattr(row.report, filters.sort)
        return getattr(row.report.metrics, filters.sort, None)

    known, missing = [], []
    for row in rows:
        value = sort_value(row)
        if value is None:
            missing.append(row)
        else:
            known.append((value, row))
    known.sort(key=lambda item: item[0], reverse=filters.direction == "desc")
    ordered = [row for _, row in known] + missing
    offset = (filters.page - 1) * filters.page_size
    return Page(
        items=ordered[offset:offset + filters.page_size],
        page=filters.page,
        page_size=filters.page_size,
        total=len(ordered),
    )
