from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.detection_config import DetectionConfig
from app.detection_evidence import CampaignFacts, Observation, reporting_windows
from app.detection_policies import evaluate_campaign
from app.domain import CANONICAL_CONTEXT
from app.metrics import Totals

D = Decimal
CONFIG = DetectionConfig.model_construct()
WINDOWS = reporting_windows(date(2026, 11, 23), CONFIG)
CAMPAIGN = CampaignFacts(1, "example", "Example", "GOOGLE_ADS", "PURCHASES", "USD",
                         date(2026, 8, 25), None, D(25), D(2))


def week(window, *, impressions=20_000, clicks=1_000, spend="500", purchases="100", value="1000", context=CANONICAL_CONTEXT):
    first = Totals(impressions - 6, clicks, D(spend), D(purchases), D(value))
    return [Observation(day, context, first if day == window.start else Totals(impressions=1))
            for day in sorted(window.dates())]


def evaluate(current=None, baseline=None, *, campaign=CAMPAIGN, configuration=CONFIG):
    rows = [*(current if current is not None else week(WINDOWS.current)),
            *(baseline if baseline is not None else week(WINDOWS.baseline))]
    findings, suppressions = evaluate_campaign(campaign, rows, WINDOWS, configuration)
    return {row["policy_id"]: row for row in findings}, {row.policy_id: row for row in suppressions}


def test_windows_have_equal_weekdays_and_lag_excludes_today():
    assert WINDOWS.current.start == date(2026, 11, 9)
    assert WINDOWS.current.end == date(2026, 11, 15)
    assert WINDOWS.baseline.start == date(2026, 11, 2)
    assert WINDOWS.baseline.end == date(2026, 11, 8)
    assert len(WINDOWS.history.dates()) == 28
    lagged = reporting_windows(date(2026, 11, 23), CONFIG.model_copy(update={"maturation_days": 10}))
    assert lagged.current.end == date(2026, 11, 12)
    with pytest.raises(ValueError):
        DetectionConfig(maturation_days=6)


@pytest.mark.parametrize(("spend", "triggers"), [("42", True), ("41.9999", False)])
def test_d01_cpa_boundary_with_repeating_ratios(spend, triggers):
    findings, _ = evaluate(
        week(WINDOWS.current, spend=spend, purchases="21"),
        week(WINDOWS.baseline, spend="35", purchases="21"),
    )
    assert ("D-01" in findings) is triggers
    if triggers:
        finding = findings["D-01"]
        assert D(finding["observations"]["cpa_change_pct"]) == 20
        assert finding["severity"] == "MEDIUM"
        assert D(finding["current_evidence"]["metrics"]["spend"]) == 42


def test_d01_high_spend_priority_and_undefined_baseline():
    findings, _ = evaluate(week(WINDOWS.current, spend="500"), week(WINDOWS.baseline, spend="400"))
    assert findings["D-01"]["severity"] == "HIGH"
    findings, suppressions = evaluate(baseline=week(WINDOWS.baseline, spend="0"))
    assert "D-01" not in findings
    assert suppressions["D-01"].reason_code == "UNDEFINED_METRIC"


@pytest.mark.parametrize(("value", "triggers"), [("510", True), ("510.0001", False)])
def test_d02_target_boundary_uses_only_current_period(value, triggers):
    findings, suppressions = evaluate(week(WINDOWS.current, clicks=100, purchases="10", spend="300", value=value), [])
    assert ("D-02" in findings) is triggers
    assert suppressions["D-01"].reason_code == "DATA_QUALITY_BLOCKED"
    if triggers:
        assert findings["D-02"]["baseline_evidence"] is None
        assert D(findings["D-02"]["observations"]["roas_target_deviation_pct"]) == -15


def test_missing_target_and_volume_suppress_without_inventing_values():
    findings, suppressions = evaluate(campaign=replace(CAMPAIGN, target_roas=None))
    assert "D-02" not in findings and "D-05" not in findings
    assert suppressions["D-02"].reason_code == "MISSING_ROAS_TARGET"
    assert suppressions["D-05"].reason_code == "MISSING_ROAS_TARGET"
    _, suppressions = evaluate(week(WINDOWS.current, clicks=99, purchases="9"))
    assert suppressions["D-01"].reason_code == "INSUFFICIENT_VOLUME"
    assert suppressions["D-02"].reason_code == "INSUFFICIENT_VOLUME"


def test_d03_exact_cvr_and_ctr_boundaries_and_unstable_ctr():
    baseline = week(WINDOWS.baseline, clicks=1000, purchases="200")
    findings, _ = evaluate(week(WINDOWS.current, clicks=1100, purchases="187"), baseline)
    finding = findings["D-03"]
    assert D(finding["observations"]["cvr_change_pct"]) == -15
    assert D(finding["observations"]["ctr_change_pct"]) == 10
    assert "cpc_change_pct" in finding["observations"]
    findings, suppressions = evaluate(week(WINDOWS.current, clicks=1101, purchases="187"), baseline)
    assert "D-03" not in findings
    assert suppressions["D-03"].reason_code == "UNSTABLE_CTR"


@pytest.mark.parametrize(("spend", "severity"), [("299.9999", None), ("300", "MEDIUM"), ("1000", "HIGH")])
def test_d04_uses_zero_not_volume_gate(spend, severity):
    findings, _ = evaluate(week(WINDOWS.current, clicks=50, spend=spend, purchases="0", value="0"))
    assert findings.get("D-04", {}).get("severity") == severity


def test_d04_separates_absent_invalid_and_zero_credit():
    current = week(WINDOWS.current, spend="300", purchases="0", value="0")
    findings, suppressions = evaluate(current[:-1])
    assert "D-04" not in findings
    assert findings["D-06"]["severity"] == "HIGH"
    assert suppressions["D-04"].reason_code == "DATA_QUALITY_BLOCKED"
    for value in (None, D("NaN")):
        invalid = [replace(current[0], totals=replace(current[0].totals, attributed_purchases=value)), *current[1:]]
        findings, suppressions = evaluate(invalid)
        assert findings["D-06"]["current_evidence"]["metrics"]["attributed_purchases"] is None
        assert findings["D-06"]["data_quality_flags"][0]["code"] == "UNUSABLE_CONVERSION_VALUES"
        assert suppressions["D-04"].reason_code == "DATA_QUALITY_BLOCKED"


def test_d05_target_boundary_stability_and_opportunity_classification():
    campaign = replace(CAMPAIGN, target_roas=D("2.5"))
    now = week(WINDOWS.current, spend="500", value="1500")
    findings, _ = evaluate(now, week(WINDOWS.baseline, spend="400", purchases="80", value="1200"), campaign=campaign)
    finding = findings["D-05"]
    assert finding["category"] == "OPTIMIZATION_OPPORTUNITY"
    assert finding["severity"] == "LOW"
    assert D(finding["observations"]["spend_change_pct"]) == 25
    assert D(finding["observations"]["roas_target_deviation_pct"]) == 20
    findings, suppressions = evaluate(now, week(WINDOWS.baseline, spend="399.9999", purchases="80", value="1200"), campaign=campaign)
    assert "D-05" not in findings
    assert suppressions["D-05"].reason_code == "UNSTABLE_RECENT_PERFORMANCE"
    _, suppressions = evaluate(now, week(WINDOWS.baseline, spend="299", value="897"), campaign=campaign)
    assert suppressions["D-05"].reason_code == "INSUFFICIENT_SPEND_HISTORY"


def test_d06_context_mismatch_blocks_comparisons_but_not_valid_current_target():
    now = week(WINDOWS.current, value="500")
    prior = week(WINDOWS.baseline, context=replace(CANONICAL_CONTEXT, attribution_method="LINEAR"))
    findings, suppressions = evaluate(now, prior)
    assert "D-02" in findings
    assert findings["D-06"]["severity"] == "MEDIUM"
    assert any(flag["code"] == "INCOMPATIBLE_COMPARISON_CONTEXT" for flag in findings["D-06"]["data_quality_flags"])
    assert all(suppressions[policy].reason_code == "DATA_QUALITY_BLOCKED" for policy in ("D-01", "D-03", "D-05"))


def test_d06_unknown_context_is_blocking_and_discontinuity_is_advisory():
    findings, suppressions = evaluate(week(WINDOWS.current, context=replace(CANONICAL_CONTEXT, attribution_method="UNKNOWN")))
    assert findings["D-06"]["data_quality_flags"][0]["code"] == "UNKNOWN_ATTRIBUTION"
    assert suppressions["D-02"].reason_code == "DATA_QUALITY_BLOCKED"
    findings, _ = evaluate(week(WINDOWS.current, purchases="0", value="0"))
    assert findings["D-06"]["severity"] == "LOW"
    assert findings["D-06"]["data_quality_flags"][0]["code"] == "PURCHASE_DISCONTINUITY"
    assert "D-04" in findings


def test_d06_delivery_discontinuity_requires_the_configured_trailing_day_count():
    current = week(WINDOWS.current)
    for count in (2, 3):
        rows = [*current[:-count], *(replace(row, totals=Totals()) for row in current[-count:])]
        findings, _ = evaluate(rows)
        if count == 2:
            assert "D-06" not in findings
        else:
            [flag] = findings["D-06"]["data_quality_flags"]
            assert flag["code"] == "DELIVERY_DISCONTINUITY" and not flag["blocking"]
            assert len(flag["dates"]) == 3


def test_earliest_lifecycle_days_are_not_labeled_as_missing():
    start = date(2026, 11, 10)
    campaign = replace(CAMPAIGN, start_date=start)
    current = [row for row in week(WINDOWS.current) if row.date >= start]
    findings, suppressions = evaluate(current, [], campaign=campaign)
    assert "D-06" not in findings
    assert suppressions["D-02"].reason_code == "INCOMPLETE_WINDOW"
