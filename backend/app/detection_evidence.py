from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field

from app.detection_config import DetectionConfig
from app.domain import CANONICAL_CONTEXT, CONTEXT_OPTIONS, ReportingContext
from app.metrics import Metrics, Totals, calculate, sum_totals


class Window(BaseModel):
    start: date
    end: date

    def dates(self) -> set[date]:
        return {self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)}


class Windows(BaseModel):
    current: Window
    baseline: Window
    history: Window
    maturation_days: int


def reporting_windows(evaluation_date: date, configuration: DetectionConfig) -> Windows:
    end = evaluation_date - timedelta(days=configuration.maturation_days + 1)
    return Windows(
        current=Window(start=end - timedelta(days=6), end=end),
        baseline=Window(start=end - timedelta(days=13), end=end - timedelta(days=7)),
        history=Window(start=end - timedelta(days=41), end=end - timedelta(days=14)),
        maturation_days=configuration.maturation_days,
    )


@dataclass(frozen=True)
class CampaignFacts:
    id: int
    external_campaign_id: str
    campaign_name: str
    platform: str
    objective: str
    currency: str
    start_date: date
    end_date: date | None
    target_cpa: Decimal | None
    target_roas: Decimal | None


@dataclass(frozen=True)
class Observation:
    date: date
    context: ReportingContext
    totals: Totals
    fictional: bool = False


class QualityFlag(BaseModel):
    code: str
    period: str
    message: str
    dates: list[date] = Field(default_factory=list)
    blocking: bool


class PeriodEvidence(BaseModel):
    start: date
    end: date
    calendar_days: int
    expected_days: int
    observed_days: int
    fictional_days: int
    missing_dates: list[date]
    complete: bool
    metrics: Metrics | None


def finite_nonnegative(value: Decimal | int | None) -> bool:
    if not isinstance(value, (Decimal, int)):
        return False
    return (not isinstance(value, Decimal) or value.is_finite()) and value >= 0


def inspect_period(campaign: CampaignFacts, source: list[Observation], window: Window, period: str):
    dates = window.dates()
    expected = {day for day in dates if campaign.start_date <= day and (not campaign.end_date or day <= campaign.end_date)}
    observations = [row for row in source if row.date in dates]
    counts = Counter(row.date for row in observations)
    observed = expected.intersection(counts)
    missing = expected - observed
    issues: list[QualityFlag] = []

    def flag(code: str, message: str, days=(), *, blocking: bool = True):
        issues.append(QualityFlag(code=code, period=period, message=message, dates=sorted(days),
                                  blocking=blocking and period != "history"))

    if missing:
        flag("MISSING_REPORTING_DAYS", "Expected campaign dates have no persisted daily record.", missing)
    if outside := set(counts) - expected:
        flag("OUTSIDE_CAMPAIGN_DATES", "Daily records fall outside the recorded campaign lifetime.", outside)
    if repeated := {day for day, count in counts.items() if count > 1}:
        flag("DUPLICATE_REPORTING_DAYS", "More than one observation shares a campaign reporting date.", repeated)

    contexts = {row.context for row in observations}
    unknown = {
        row.date for row in observations
        if any(getattr(row.context, field) in (None, "", "UNKNOWN") for field in CONTEXT_OPTIONS)
    }
    if unknown:
        flag("UNKNOWN_ATTRIBUTION", "The reporting definition has missing or unknown attribution metadata.", unknown)
    unsupported = {
        row.date for row in observations if row.date not in unknown and (
            any(getattr(row.context, field) not in options for field, options in CONTEXT_OPTIONS.items())
            or row.context.conversion_action != CANONICAL_CONTEXT.conversion_action
            or row.context.attribution_window != CANONICAL_CONTEXT.attribution_window
            or row.context.date_basis != CANONICAL_CONTEXT.date_basis
        )
    }
    if unsupported:
        flag("UNSUPPORTED_ATTRIBUTION", "The conversion action, window, or date basis cannot be evaluated safely.", unsupported)
    if len(contexts) > 1:
        flag("MIXED_REPORTING_CONTEXT", "Daily observations use different reporting definitions.", counts)

    invalid_traffic = {
        row.date for row in observations if not all(finite_nonnegative(value) for value in
            (row.totals.impressions, row.totals.clicks, row.totals.spend))
        or row.totals.clicks > row.totals.impressions
    }
    invalid_conversions = {
        row.date for row in observations if not all(finite_nonnegative(value) for value in
            (row.totals.attributed_purchases, row.totals.attributed_purchase_value))
    }
    if invalid_traffic:
        flag("INVALID_TRAFFIC_OR_SPEND", "Traffic or spend is absent, non-finite, negative, or contradictory.", invalid_traffic)
    if invalid_conversions:
        flag("UNUSABLE_CONVERSION_VALUES", "Purchase credit or value is absent, non-finite, or negative.", invalid_conversions)

    metrics = None
    if observations and not (invalid_traffic or repeated or outside):
        totals = sum_totals(row.totals for row in observations) if not invalid_conversions else sum_totals(
            Totals(row.totals.impressions, row.totals.clicks, row.totals.spend) for row in observations
        )
        valid_conversion_context = not (invalid_conversions or unknown or unsupported or len(contexts) > 1)
        if valid_conversion_context and totals.attributed_purchase_value > 0 and totals.attributed_purchases == 0:
            flag("VALUE_WITHOUT_PURCHASE_CREDIT", "Attributed purchase value is positive while total purchase credit is zero.", counts)
            valid_conversion_context = False
        if valid_conversion_context and totals.attributed_purchases > 0 and totals.attributed_purchase_value == 0:
            flag("ZERO_VALUE_WITH_PURCHASES", "Purchase credit is present with zero attributed value. Confirm whether zero-value orders are expected.", counts, blocking=False)
        metrics = calculate(totals, conversions_available=valid_conversion_context)

    return PeriodEvidence(
        start=window.start, end=window.end, calendar_days=len(dates), expected_days=len(expected),
        observed_days=len(observed), fictional_days=len({row.date for row in observations if row.fictional and row.date in observed}),
        missing_dates=sorted(missing),
        complete=(expected == dates and not (missing or repeated or outside)), metrics=metrics,
    ), contexts, issues


@dataclass(frozen=True)
class Evidence:
    current: PeriodEvidence
    baseline: PeriodEvidence
    history: PeriodEvidence
    contexts: list[dict]
    flags: list[QualityFlag]


def prepare_evidence(campaign: CampaignFacts, source: list[Observation], windows: Windows,
                     configuration: DetectionConfig) -> Evidence:
    current, current_contexts, flags = inspect_period(campaign, source, windows.current, "current")
    baseline, baseline_contexts, base_flags = inspect_period(campaign, source, windows.baseline, "baseline")
    history, _, history_flags = inspect_period(campaign, source, windows.history, "history")
    # Older incomplete coverage is useful context. The two evaluated weeks govern the rules.
    flags.extend(base_flags)
    flags.extend(flag for flag in history_flags if flag.code != "MISSING_REPORTING_DAYS")
    if current_contexts and baseline_contexts and current_contexts != baseline_contexts:
        flags.append(QualityFlag(
            code="INCOMPATIBLE_COMPARISON_CONTEXT", period="comparison", blocking=True,
            message="Current and baseline observations use different reporting definitions.",
        ))
    if campaign.objective != "PURCHASES" or campaign.currency != "USD" or any(
        target is not None and (not finite_nonnegative(target) or target == 0)
        for target in (campaign.target_cpa, campaign.target_roas)
    ):
        flags.append(QualityFlag(
            code="INVALID_CAMPAIGN_METADATA", period="current", blocking=True,
            message="The campaign objective, currency, or configured efficiency targets are invalid.",
        ))

    now, prior = current.metrics, baseline.metrics
    if current.complete and baseline.complete and now and prior:
        days = configuration.quality_zero_delivery_days
        first = windows.current.end - timedelta(days=days - 1)
        trailing = [row for row in source if first <= row.date <= windows.current.end]
        if len(trailing) == days and prior.clicks >= configuration.min_clicks and all(row.totals.impressions == 0 for row in trailing):
            flags.append(QualityFlag(
                code="DELIVERY_DISCONTINUITY", period="current", blocking=False,
                message=f"{days} consecutive trailing days reported zero impressions after recent delivery. Review delivery and reporting.",
                dates=sorted(row.date for row in trailing),
            ))
        if (now.clicks >= configuration.min_clicks and now.attributed_purchases == 0
                and prior.attributed_purchases is not None
                and prior.attributed_purchases >= configuration.min_purchases):
            flags.append(QualityFlag(
                code="PURCHASE_DISCONTINUITY", period="current", blocking=False,
                message="Observed purchase credit fell to zero while clicks continued. Confirm whether reporting or delivery changed.",
                dates=sorted(windows.current.dates()),
            ))
    ordered_contexts = sorted(current_contexts | baseline_contexts, key=lambda context: tuple(str(x) for x in asdict(context).values()))
    return Evidence(current, baseline, history, [asdict(context) for context in ordered_contexts], flags)
