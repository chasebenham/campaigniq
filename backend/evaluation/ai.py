"""Run offline AI contract cases using independently specified fictional observations and references."""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.ai_contract import build_snapshot, references, validate_output
from app.detection import canonical_json, fingerprint
from app.detection_config import DetectionConfig
from app.detection_evidence import CampaignFacts, Observation, reporting_windows
from app.detection_models import DetectionFinding
from app.detection_policies import evaluate_campaign
from app.domain import CANONICAL_CONTEXT
from app.metrics import Totals

CASES = Path(__file__).with_name("ai_cases.json")


def reference_matches(actual, expected) -> bool:
    if isinstance(expected, str):
        try:
            return Decimal(actual) == Decimal(expected)
        except (InvalidOperation, TypeError):
            return actual == expected
    return type(actual) is type(expected) and actual == expected


def evaluate_cases() -> list[dict]:
    config = DetectionConfig.model_construct()
    windows = reporting_windows(date(2026, 11, 23), config)
    results = []
    for index, case in enumerate(json.loads(CASES.read_text(encoding="utf-8")), start=1):
        def observations(window, values):
            first = Totals(19994, values.get("clicks", 1000), Decimal(values["spend"]),
                           Decimal(values["purchases"]), Decimal(values["value"]))
            days = sorted(window.dates())[:7 - values.get("missing_days", 0)]
            return [Observation(day, CANONICAL_CONTEXT, first if n == 0 else Totals(impressions=1), fictional=True)
                    for n, day in enumerate(days)]

        campaign = CampaignFacts(index, f"fictional-{case['case']}", "Fictional evaluation campaign",
                                 "GOOGLE_ADS", "PURCHASES", "USD", date(2026, 8, 25),
                                 None, Decimal(25), Decimal(case.get("target_roas", "2")))
        findings, suppressed = evaluate_campaign(campaign, [
            *observations(windows.baseline, case["baseline"]), *observations(windows.current, case["current"]),
        ], windows, config)
        detected = next((row for row in findings if row["policy_id"] == case["policy"]), None)
        if "expected_suppression" in case:
            assert detected is None and any(item.policy_id == case["policy"] and item.reason_code == case["expected_suppression"]
                                            for item in suppressed), case["case"]
            results.append({"case": case["case"], "result": "SUPPRESSION_HAS_NO_ANALYSIS_TARGET"})
            continue
        assert detected is not None, case["case"]
        detected["campaign_snapshot"] = json.loads(canonical_json(detected["campaign_snapshot"]))
        finding = DetectionFinding(id=index, run_id=1, campaign_id=index, fingerprint=fingerprint(detected), **detected)
        snapshot = build_snapshot(finding)
        values = references(snapshot)
        assert all(path in values and reference_matches(values[path], expected)
                   for path, expected in case["expected_values"].items()), case["case"]
        experiment = None
        if case["action"] in {"TEST", "CONSIDER_REALLOCATION"}:
            experiment = {
                "design": "Compare a single treatment with an unchanged control.",
                "proposed_change": "Change the spend or purchase flow in the treatment only.",
                "comparison": "Keep the control's settings and measurement unchanged.",
                "audience_or_scope": "Assign comparable eligible audience segments.",
                "duration": "Set the observation window before launch and allow conversion maturation.",
                "guardrails": "Cap the treatment spend and stop for tracking errors.",
                "guardrail_metrics": ["CPA", "Treatment spend"],
                "decision_rule": "Compare performance against the control after evidence requirements are met.",
            }
        validate_output({
            "finding_id": index,
            "executive_summary": case["summary"],
            "business_impact_assessment": "The observed metric or reporting issue warrants analyst review.",
            "evidence_references": case["references"],
            "possible_explanations": ["Delivery mix may have shifted.", "Confirm whether reporting or measurement changed."],
            "missing_information": ["Campaign changes and order-level reconciliation."],
            "recommended_action_type": case["action"],
            "recommended_action": case["next_step"],
            "action_rationale": "Confirm the relevant evidence before changing the campaign.",
            "experiment_hypothesis": "A controlled test can measure the effect of the proposed change." if experiment else None,
            "proposed_experiment": experiment,
            "primary_success_metric": ("Marginal attributed return" if case["policy"] == "D-05" else "Purchase CVR") if experiment else None,
            "secondary_metrics": ["Attributed purchase credit"] if experiment else [],
            "risks_and_limitations": ["Platform reporting cannot establish incremental revenue or causal effects."],
            "confidence_rationale": "The referenced observation is measured. The cause and future impact remain uncertain.",
        }, snapshot)
        results.append({"case": case["case"], "result": "FIXTURE_CONTRACT_PASSED", "policy": case["policy"]})
    return results


if __name__ == "__main__":
    print(json.dumps({"provider_called": False, "results": evaluate_cases()}, indent=2))
