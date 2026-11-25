"""Deterministic allocation and piecewise CPA modeling."""

from decimal import Decimal, ROUND_FLOOR, localcontext

from app.budget.benchmarks import BudgetError
from app.budget.schemas import (
    CENT, HUNDRED, MODEL_VERSION, Allocation, AllocationRow, Benchmark, BudgetWarning,
    Calculation, CampaignOutcome, CaseAssumption, HistoricalAllocation, Mode, Outcome,
    OutcomeDelta, Plan, ScenarioOutcome,
)
from app.metrics import ratio

ZERO = Decimal(0)
CASE_NAMES = ("conservative", "base", "optimistic")


def exact_split(units: int, weights: dict[int, Decimal]) -> dict[int, int]:
    """Allocate integer cents or basis points using largest remainders and stable ID ties."""
    with localcontext() as ctx:
        ctx.prec = 60
        total = sum(weights.values(), ZERO)
        if total == 0:
            return dict.fromkeys(weights, 0)
        shares = {key: units * value / total for key, value in weights.items()}
        floors = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in shares.items()}
        order = sorted(weights, key=lambda key: (floors[key] - shares[key], key))
        for key in order[:units - sum(floors.values())]:
            floors[key] += 1
    return floors


def checked_eligible(benchmarks: list[Benchmark]) -> set[int]:
    eligible = {row.campaign_id for row in benchmarks if row.eligible}
    if len(eligible) < 2:
        raise BudgetError("INSUFFICIENT_ELIGIBLE_CAMPAIGNS", "Select at least two eligible campaigns for a comparison.")
    return eligible


def manual_weights(items: list[Allocation], eligible: set[int]) -> dict[int, Decimal]:
    values = {row.campaign_id: row.value for row in items}
    if any(value and key not in eligible for key, value in values.items()):
        raise BudgetError("INELIGIBLE_ALLOCATION", "Only eligible campaigns may receive a budget. Set blocked allocations to zero.")
    return values


def allocation_rows(budget: Decimal, weights: dict[int, Decimal], eligible: set[int],
                    mode: Mode | None = None) -> list[AllocationRow]:
    cents = int(budget / CENT)
    if mode == "DOLLARS":
        dollars = weights
    else:
        dollars = {key: amount * CENT for key, amount in exact_split(cents, weights).items()}
    if mode == "PERCENT":
        percentages = weights
    else:
        basis = weights if any(weights.values()) else {key: Decimal(key in eligible) for key in weights}
        percentages = {key: amount * CENT for key, amount in exact_split(10_000, basis).items()}
    return [AllocationRow(campaign_id=key, dollars=dollars[key], percent=percentages[key]) for key in sorted(weights)]


def outcome(spend: Decimal, purchases: Decimal | None, value: Decimal | None) -> Outcome:
    return Outcome(spend=spend, purchases=purchases, value=value,
                   cpa=ratio(spend, purchases) if purchases else None,
                   roas=ratio(value, spend) if value is not None else None)


def aggregate(rows: list[Outcome], compatible: bool) -> Outcome:
    spend = sum((row.spend for row in rows), ZERO)
    if not compatible:
        return outcome(spend, None, None)
    purchases = sum((row.purchases for row in rows if row.purchases is not None), ZERO)
    value = sum((row.value for row in rows if row.value is not None), ZERO)
    return outcome(spend, purchases, value)


def delta(after: Outcome, before: Outcome) -> OutcomeDelta:
    changes = {key: (a - b if a is not None and b is not None else None)
               for key in Outcome.model_fields if key != "spend"
               for a, b in [(getattr(after, key), getattr(before, key))]}
    return OutcomeDelta(spend=after.spend - before.spend, **changes)


def piecewise(budget: Decimal, historical: Decimal, cpa: Decimal, value_per_purchase: Decimal,
              assumption: CaseAssumption) -> Outcome:
    with localcontext() as ctx:
        ctx.prec = 48
        adjusted_cpa = cpa * (1 + assumption.cpa_change_pct / HUNDRED)
        marginal_cpa = adjusted_cpa * (1 + assumption.marginal_cpa_change_pct / HUNDRED)
        purchases = min(budget, historical) / adjusted_cpa + max(ZERO, budget - historical) / marginal_cpa
        value = purchases * value_per_purchase * (1 + assumption.value_per_purchase_change_pct / HUNDRED)
        return outcome(budget, purchases, value)


def extrapolation(planned: Decimal, normal: Decimal):
    if planned <= normal:
        return "none"
    if planned <= normal * Decimal("1.10"):
        return "modest"
    if planned <= normal * Decimal("1.50"):
        return "elevated"
    return "substantial"


def compatible(rows: list[Benchmark]) -> bool:
    contexts = {context for row in rows for context in row.attribution_contexts}
    return len(contexts) <= 1 and all(
        row.period.metrics and row.period.metrics.attributed_purchases is not None for row in rows
    )


def normalized(benchmark: Benchmark, planning_days: int) -> Outcome:
    if not benchmark.eligible:
        return outcome(ZERO, None, None)
    metrics = benchmark.period.metrics
    days = benchmark.period.observed_days
    return Outcome(
        spend=metrics.spend * planning_days / days,
        purchases=metrics.attributed_purchases * planning_days / days,
        value=metrics.attributed_purchase_value * planning_days / days,
        cpa=metrics.cpa, roas=metrics.roas,
    )


def calculate_plan(plan: Plan, benchmarks: list[Benchmark], digest: str, minimum: int, lag: int) -> Calculation:
    with localcontext() as ctx:
        ctx.prec = 48
        return _calculate(plan, benchmarks, digest, minimum, lag)


def _calculate(plan: Plan, benchmarks: list[Benchmark], digest: str, minimum: int, lag: int) -> Calculation:
    eligible = checked_eligible(benchmarks)
    weights = manual_weights(plan.allocations, eligible)
    dollars = {row.campaign_id: row.dollars for row in allocation_rows(plan.total_budget, weights, eligible, plan.mode)}
    historic = {row.campaign_id: normalized(row, plan.planning.days) for row in benchmarks}
    actual = {row.campaign_id: outcome(row.period.metrics.spend, row.period.metrics.attributed_purchases,
                                      row.period.metrics.attributed_purchase_value) if row.period.metrics
              else outcome(ZERO, None, None) for row in benchmarks}
    eligible_rows = [row for row in benchmarks if row.eligible]
    allocated_rows = [row for row in eligible_rows if dollars[row.campaign_id] > 0]
    history_compatible = compatible(eligible_rows)
    modeled_compatible = compatible(allocated_rows)
    observed = aggregate(list(actual.values()), compatible(benchmarks))
    baseline = aggregate([historic[key] for key in sorted(eligible)], history_compatible)
    warnings = []

    def warn(code, message, campaign_id=None, scenario=None, severity="warning"):
        warnings.append(BudgetWarning(code=code, message=message, campaign_id=campaign_id, scenario=scenario, severity=severity))

    known_contexts = {context for row in benchmarks for context in row.attribution_contexts}
    if len(known_contexts) > 1:
        warn("ATTRIBUTION_CONTEXTS_DIFFER", "Selected campaigns report under different attribution definitions. Blended conversion measures are withheld for groups with incompatible definitions.")
    if len({row.platform for row in benchmarks}) > 1:
        warn("CROSS_PLATFORM_ATTRIBUTION", "Platform-attributed credit can overlap across Google Ads and Meta Ads. Unique customers, incremental return and profit require separate evidence.")
    if any(row.period.fictional_days for row in benchmarks):
        warn("FICTIONAL_DATA", "Historical benchmarks include fictional Northstar Outfitters observations.", severity="notice")

    allocation = []
    for row in benchmarks:
        key = row.campaign_id
        b, h = dollars[key], historic[key]
        threshold = extrapolation(b, h.spend) if row.eligible else None
        observed_share = ratio(actual[key].spend, observed.spend, 100) or ZERO
        normalized_share = ratio(h.spend, baseline.spend, 100) or ZERO
        planned_share = ratio(b, plan.total_budget, 100) or ZERO
        allocation.append(HistoricalAllocation(
            campaign_id=key, observed_share_pct=observed_share, normalized_share_pct=normalized_share,
            planned_share_pct=planned_share, share_change_pct_points=planned_share - normalized_share,
            normalized=h, planned_spend=b, spend_change=b - h.spend, extrapolation=threshold,
        ))
        if not row.eligible:
            warn("INELIGIBLE_CAMPAIGN", "This campaign is excluded from modeled outcomes. " + " ".join(row.blockers), key)
        if row.period.observed_days < minimum:
            warn("INSUFFICIENT_HISTORY", f"Fewer than {minimum} mature campaign-days support this reference period.", key)
        if row.period.observed_days < row.period.calendar_days:
            warn("INCOMPLETE_REPORTING", f"{row.period.observed_days} of {row.period.calendar_days} selected calendar days have a report. {row.period.expected_days} fell within campaign dates.", key)
        if row.flags:
            warn("DATA_QUALITY", "Review the reporting flags before interpreting this campaign’s benchmark.", key)
        if threshold and threshold != "none":
            warn(f"EXTRAPOLATION_{threshold.upper()}", f"{threshold.capitalize()} extrapolation. Proposed spending exceeds the historical daily rate normalized to this planning period.", key)
        if row.eligible and row.peak_daily_spend is not None and b > row.peak_daily_spend * plan.planning.days:
            warn("ABOVE_DAILY_PEAK", "Average planned daily spend exceeds the highest observed daily spend.", key)
        if b and (b - h.spend) >= b * Decimal("0.25"):
            warn("HIGH_INCREMENTAL_EXPOSURE", "At least a quarter of planned spending is above the normalized historical level and depends on the marginal CPA assumption.", key)
    incremental = sum((max(ZERO, dollars[key] - historic[key].spend) for key in eligible), ZERO)
    if plan.total_budget and incremental >= plan.total_budget * Decimal("0.25"):
        warn("PORTFOLIO_INCREMENTAL_EXPOSURE", "At least a quarter of portfolio spend is above campaign historical levels and depends on marginal CPA assumptions.")

    models = {}
    for name in CASE_NAMES:
        assumption = getattr(plan.assumptions, name)
        if abs(assumption.cpa_change_pct) >= 25 or abs(assumption.value_per_purchase_change_pct) >= 20 or assumption.marginal_cpa_change_pct >= 50:
            warn("SUBSTANTIAL_ASSUMPTIONS", "This case uses a substantial CPA, marginal CPA, or attributed value adjustment.", scenario=name)
        modeled = []
        for row in benchmarks:
            key = row.campaign_id
            h = historic[key]
            m = outcome(ZERO, None, None)
            if row.eligible:
                metrics = row.period.metrics
                m = piecewise(dollars[key], h.spend, metrics.cpa, metrics.attributed_aov, assumption)
            modeled.append(CampaignOutcome(campaign_id=key, modeled=m, delta=delta(m, h)))
        portfolio = aggregate([entry.modeled for entry in modeled if entry.campaign_id in eligible], modeled_compatible)
        models[name] = (portfolio, modeled)
    base_outcome = models["base"][0]
    return Calculation(
        model_version=MODEL_VERSION, evidence_fingerprint=digest, reference_days=plan.reference.days,
        planning_days=plan.planning.days, minimum_observed_days=minimum, maturation_days=lag,
        benchmarks=benchmarks, allocation=allocation, observed=observed, normalized=baseline, warnings=warnings,
        scenarios={name: ScenarioOutcome(portfolio=portfolio, campaigns=modeled, delta=delta(portfolio, baseline),
                                         versus_base=delta(portfolio, base_outcome))
                   for name, (portfolio, modeled) in models.items()},
    )
