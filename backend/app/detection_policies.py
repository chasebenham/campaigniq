from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext

from app.detection_config import POLICY_VERSION, DetectionConfig
from app.detection_evidence import CampaignFacts, Evidence, Observation, Windows, prepare_evidence
from app.metrics import Metrics, ratio

POLICIES = ("D-01", "D-02", "D-03", "D-04", "D-05", "D-06")
COMPARISON_POLICIES = {"D-01", "D-03", "D-05"}
PURCHASE_VOLUME_POLICIES = {"D-01", "D-02", "D-03", "D-05"}

TITLES = {
    "D-01": "CPA deterioration",
    "D-02": "ROAS below target",
    "D-03": "Purchase conversion rate decline",
    "D-04": "Spend without attributed purchases",
    "D-05": "Potential scaling opportunity",
    "D-06": "Reporting or data-quality issue",
}
ATTRIBUTION_LIMIT = "Purchase credit and value are platform-attributed. This evidence cannot establish incremental revenue, profit, or unique customer counts."
LIMITS = {
    "D-01": "The comparison describes a change in observed acquisition cost. The evidence does not establish its cause.",
    "D-02": "The comparison uses the campaign’s configured target and the evaluated period’s attributed value.",
    "D-03": "Stable CTR with lower observed purchase CVR identifies where to investigate. Landing-page or creative causality requires additional evidence.",
    "D-04": "Reported zero purchase credit is distinct from absent observations. Verify measurement and delivery before changing spend.",
    "D-05": "Average historical ROAS and CPA do not establish marginal returns. A controlled test is needed to evaluate additional spend.",
    "D-06": "Data-quality flags describe the observed integrity signal. A discontinuity alone cannot identify a tracking failure.",
}


@dataclass(frozen=True)
class Outcome:
    policy_id: str
    magnitude: Decimal
    observations: dict
    thresholds: dict


@dataclass(frozen=True)
class Suppression:
    policy_id: str
    reason_code: str
    explanation: str
    evidence: dict


def change(actual: Decimal | None, reference: Decimal | None) -> Decimal | None:
    if actual is None or reference is None or reference <= 0:
        return None
    return ratio(actual - reference, reference, 100)


@dataclass(frozen=True)
class RelativeChange:
    numerator: Decimal
    denominator: Decimal

    @classmethod
    def compare(cls, actual, actual_base, baseline, baseline_base):
        if actual is None or baseline is None or not actual_base or not baseline_base or baseline <= 0:
            return None
        reference = Decimal(baseline) * actual_base
        return cls((Decimal(actual) * baseline_base - reference) * 100, reference)

    def percent(self) -> Decimal:
        return ratio(self.numerator, self.denominator)


def substantial(metrics: Metrics | None, c: DetectionConfig) -> bool:
    return bool(metrics and metrics.clicks >= c.min_clicks and metrics.attributed_purchases is not None
                and metrics.attributed_purchases >= c.min_purchases)


def evaluate_policy(policy: str, campaign: CampaignFacts, evidence: Evidence, c: DetectionConfig) -> Outcome | Suppression | None:
    now, prior = evidence.current.metrics, evidence.baseline.metrics
    comparison = policy in COMPARISON_POLICIES
    current_json = evidence.current.model_dump(mode="json")
    baseline_json = evidence.baseline.model_dump(mode="json") if comparison else None
    blocker_periods = {"current", "baseline", "comparison"} if comparison else {"current"}
    blockers = [flag.model_dump(mode="json") for flag in evidence.flags if flag.blocking and flag.period in blocker_periods]

    def suppressed(code: str, message: str, **details):
        return Suppression(policy, code, message, {"current": current_json, "baseline": baseline_json, **details})

    if policy == "D-06":
        if not evidence.flags:
            return None
        return Outcome(policy, Decimal(sum(flag.blocking for flag in evidence.flags)), {
            "flag_count": len(evidence.flags),
            "blocking_flag_count": sum(flag.blocking for flag in evidence.flags),
        }, {"maturation_days": c.maturation_days, "delivery_zero_days": c.quality_zero_delivery_days,
            "discontinuity_min_clicks": c.min_clicks, "discontinuity_min_purchases": str(c.min_purchases)})

    if blockers:
        return suppressed("DATA_QUALITY_BLOCKED", "A data-quality blocker prevents this rule from escalating.", blockers=blockers)
    if not evidence.current.complete or (comparison and not evidence.baseline.complete):
        return suppressed("INCOMPLETE_WINDOW", "The campaign must span every calendar day of each required period.")
    if policy in {"D-02", "D-05"} and campaign.target_roas is None:
        return suppressed("MISSING_ROAS_TARGET", "This campaign has no configured ROAS target.")
    if policy in PURCHASE_VOLUME_POLICIES and (
        not substantial(now, c) or (comparison and not substantial(prior, c))
    ):
        return suppressed("INSUFFICIENT_VOLUME", "Each applicable period requires the minimum clicks and attributed purchases.",
                          min_clicks=c.min_clicks, min_purchases=str(c.min_purchases))
    if now is None or (comparison and prior is None):
        return suppressed("UNDEFINED_METRIC", "The required reporting metrics are unavailable.")

    volume = {"min_clicks": c.min_clicks, "min_purchases": str(c.min_purchases)}
    high = {"high_risk_spend": str(c.high_risk_spend), "high_risk_deviation_pct": str(c.high_risk_deviation_pct)}

    if policy == "D-01":
        delta = RelativeChange.compare(now.spend, now.attributed_purchases, prior.spend, prior.attributed_purchases)
        if delta is None:
            return suppressed("UNDEFINED_METRIC", "CPA requires a positive baseline and valid CPA values in both periods.")
        if delta.numerator >= c.cpa_increase_pct * delta.denominator:
            return Outcome(policy, delta.percent(), {"cpa_change_pct": str(delta.percent())}, {
                **volume, **high, "cpa_increase_pct": str(c.cpa_increase_pct),
            })
    elif policy == "D-02":
        delta = RelativeChange.compare(now.attributed_purchase_value, now.spend, campaign.target_roas, 1)
        if delta is None:
            return suppressed("UNDEFINED_METRIC", "A ROAS comparison requires positive spend and a usable target.")
        if delta.numerator <= -c.roas_below_target_pct * delta.denominator:
            return Outcome(policy, -delta.percent(), {"roas_target_deviation_pct": str(delta.percent())}, {
                **volume, **high, "roas_below_target_pct": str(c.roas_below_target_pct),
            })
    elif policy == "D-03":
        cvr = RelativeChange.compare(now.attributed_purchases, now.clicks, prior.attributed_purchases, prior.clicks)
        ctr = RelativeChange.compare(now.clicks, now.impressions, prior.clicks, prior.impressions)
        if cvr is None or ctr is None:
            return suppressed("UNDEFINED_METRIC", "The observed CVR and CTR comparisons require positive baselines.")
        if cvr.numerator <= -c.cvr_decrease_pct * cvr.denominator:
            if abs(ctr.numerator) > c.ctr_stability_pct * ctr.denominator:
                return suppressed("UNSTABLE_CTR", "CTR changed beyond the allowed band for this rule.", ctr_change_pct=str(ctr.percent()))
            changes = {
                "cvr_change_pct": cvr.percent(), "ctr_change_pct": ctr.percent(),
                "cpc_change_pct": change(now.cpc, prior.cpc), "cpa_change_pct": change(now.cpa, prior.cpa),
                "click_change_pct": change(now.clicks, prior.clicks),
                "purchase_change_pct": change(now.attributed_purchases, prior.attributed_purchases),
            }
            return Outcome(policy, -cvr.percent(), {key: str(value) if value is not None else None for key, value in changes.items()}, {
                **volume, "cvr_decrease_pct": str(c.cvr_decrease_pct), "ctr_stability_pct": str(c.ctr_stability_pct),
            })
    elif policy == "D-04":
        if now.attributed_purchases is None:
            return suppressed("UNDEFINED_METRIC", "Reported purchase credit must be present to evaluate zero purchases.")
        if now.spend >= c.zero_purchase_spend and now.attributed_purchases == 0:
            return Outcome(policy, Decimal(0), {"reported_zero_purchases": True}, {
                "zero_purchase_spend": str(c.zero_purchase_spend), "high_zero_purchase_spend": str(c.high_zero_purchase_spend),
            })
    elif policy == "D-05":
        delta = RelativeChange.compare(now.attributed_purchase_value, now.spend, campaign.target_roas, 1)
        if delta is None:
            return suppressed("UNDEFINED_METRIC", "A ROAS comparison requires positive spend and a usable target.")
        if delta.numerator >= c.scaling_roas_above_target_pct * delta.denominator:
            if min(now.spend, prior.spend) < c.scaling_min_spend:
                return suppressed("INSUFFICIENT_SPEND_HISTORY", "Both evaluated periods must meet the minimum spend for a scaling opportunity.",
                                  min_spend=str(c.scaling_min_spend))
            conditions = [
                ("roas_change_pct", RelativeChange.compare(now.attributed_purchase_value, now.spend, prior.attributed_purchase_value, prior.spend), c.scaling_roas_stability_pct),
                ("cpa_change_pct", RelativeChange.compare(now.spend, now.attributed_purchases, prior.spend, prior.attributed_purchases), c.scaling_cpa_stability_pct),
                ("spend_change_pct", RelativeChange.compare(now.spend, 1, prior.spend, 1), c.scaling_spend_stability_pct),
            ]
            changes = {key: str(value.percent()) if value is not None else None for key, value, _ in conditions}
            if any(value is None or abs(value.numerator) > limit * value.denominator for _, value, limit in conditions):
                return suppressed("UNSTABLE_RECENT_PERFORMANCE", "ROAS, CPA or spend changed beyond the recent stability bands.", **changes)
            return Outcome(policy, delta.percent(), {
                "roas_target_deviation_pct": str(delta.percent()), **changes,
                "earlier_context": {"start": evidence.history.start.isoformat(), "end": evidence.history.end.isoformat(),
                                    "observed_days": evidence.history.observed_days,
                                    "expected_days": evidence.history.expected_days},
            }, {**volume, "scaling_min_spend": str(c.scaling_min_spend),
                "scaling_roas_above_target_pct": str(c.scaling_roas_above_target_pct),
                "roas_stability_pct": str(c.scaling_roas_stability_pct),
                "cpa_stability_pct": str(c.scaling_cpa_stability_pct),
                "spend_stability_pct": str(c.scaling_spend_stability_pct)})
    return None


def classification(result: Outcome, evidence: Evidence, c: DetectionConfig):
    policy = result.policy_id
    spend = evidence.current.metrics.spend if evidence.current.metrics else Decimal(0)
    category = "PERFORMANCE_RISK"
    if policy == "D-05":
        return "OPTIMIZATION_OPPORTUNITY", "LOW", "Volume and stability gates passed. Marginal efficiency remains untested."
    if policy == "D-06":
        if any(flag.blocking and flag.period == "current" for flag in evidence.flags):
            return "DATA_QUALITY", "HIGH", "A blocker affects the evaluated current period."
        if any(flag.blocking for flag in evidence.flags):
            return "DATA_QUALITY", "MEDIUM", "A blocker affects a baseline or cross-period comparison."
        if all(flag.period == "history" for flag in evidence.flags):
            return "DATA_QUALITY", "INFORMATIONAL", "The signal applies to earlier context outside the evaluated weeks."
        return "DATA_QUALITY", "LOW", "The observed signal warrants review without blocking performance rules."
    if policy in {"D-01", "D-02"}:
        if spend >= c.high_risk_spend or result.magnitude >= c.high_risk_deviation_pct:
            return category, "HIGH", "The deviation or current spend meets the elevated exposure threshold."
        return category, "MEDIUM", "The rule triggered below the elevated exposure and deviation thresholds."
    if policy == "D-04" and spend >= c.high_zero_purchase_spend:
        return category, "HIGH", "Spend reached the elevated exposure threshold with zero reported purchase credit."
    return category, "MEDIUM", "The rule and its evidence requirements were met."


def evaluate_campaign(campaign: CampaignFacts, source: list[Observation], windows: Windows,
                      configuration: DetectionConfig) -> tuple[list[dict], list[Suppression]]:
    with localcontext() as context:
        context.prec = 48
        evidence = prepare_evidence(campaign, source, windows, configuration)
        findings, suppressions = [], []
        for policy in POLICIES:
            result = evaluate_policy(policy, campaign, evidence, configuration)
            if isinstance(result, Suppression):
                suppressions.append(result)
            if not isinstance(result, Outcome):
                continue
            category, severity, reason = classification(result, evidence, configuration)
            blockers = any(flag.blocking for flag in evidence.flags)
            findings.append({
                "policy_id": policy, "policy_version": POLICY_VERSION, "category": category,
                "severity": severity, "summary": TITLES[policy], "classification_reason": reason,
                "current_evidence": evidence.current.model_dump(mode="json"),
                "baseline_evidence": evidence.baseline.model_dump(mode="json") if policy in COMPARISON_POLICIES | {"D-06"} else None,
                "campaign_snapshot": asdict(campaign),
                "thresholds": result.thresholds, "observations": result.observations,
                "reporting_context": evidence.contexts,
                "evidence_quality": "BLOCKED" if policy == "D-06" and blockers
                                    else "LIMITED" if policy in {"D-04", "D-06"} else "SUFFICIENT",
                "data_quality_flags": [flag.model_dump(mode="json") for flag in evidence.flags],
                "limitations": [LIMITS[policy], ATTRIBUTION_LIMIT],
                "spend_exposure": evidence.current.metrics.spend if evidence.current.metrics else Decimal(0),
                "magnitude": result.magnitude,
            })
        return findings, suppressions
