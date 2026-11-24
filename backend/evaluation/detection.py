"""Offline scoring of the fictional Phase 1 scenario manifest."""

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.detection import gather_inputs
from app.detection_config import POLICY_VERSION, DetectionConfig
from app.detection_evidence import reporting_windows
from app.detection_policies import POLICIES, evaluate_campaign
from app.models import Campaign

MANIFEST = Path(__file__).resolve().parents[1] / "data" / "scenario-manifest.json"
EXPECTED_POLICIES = {
    "declining_efficiency": "D-01", "inefficient_spend": "D-02",
    "conversion_decline": "D-03", "potential_scaling": "D-05", "data_quality": "D-06",
}


@dataclass(frozen=True)
class Expectation:
    campaign: str
    policy: str
    start: date
    end: date

    def matches(self, cutoff: date, finding: dict) -> bool:
        if self.policy == "D-06":
            return any(
                flag["code"] == "MISSING_REPORTING_DAYS"
                and any(self.start <= date.fromisoformat(day) <= self.end for day in flag["dates"])
                for flag in finding["data_quality_flags"]
            )
        return self.start <= cutoff <= self.end


def evaluate_seed(db: Session) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    configuration = DetectionConfig.model_construct()
    first = date.fromisoformat(manifest["first_date"])
    last = date.fromisoformat(manifest["last_date"])
    start = first + timedelta(days=13)
    cutoffs = sorted({last} | {start + timedelta(days=i) for i in range(0, (last - start).days + 1, 7)})
    names = {external_id for group in manifest["scenarios"] for external_id in group["campaign_ids"]}
    rows = list(db.execute(select(Campaign.id, Campaign.external_campaign_id).where(Campaign.external_campaign_id.in_(names))))
    if len(rows) != len(names):
        raise ValueError("Seed the unmodified Northstar portfolio into an isolated database before evaluation.")
    ids = [row.id for row in rows]
    expected = {}
    groups = {}
    for group in manifest["scenarios"]:
        for name in group["campaign_ids"]:
            groups[name] = group["group"]
            if policy := EXPECTED_POLICIES.get(group["group"]):
                dates = group.get("campaign_periods", {}).get(name, group.get("period"))
                expected[name, policy] = Expectation(name, policy, *map(date.fromisoformat, dates))

    hits = defaultdict(list)
    matches = defaultdict(list)
    suppressed = Counter()
    cohort_suppressions = Counter()
    for cutoff in cutoffs:
        windows = reporting_windows(cutoff + timedelta(days=configuration.maturation_days + 1), configuration)
        for item in gather_inputs(db, windows, campaign_ids=ids, seed_only=True):
            name = item.campaign.external_campaign_id
            findings, suppressions = evaluate_campaign(item.campaign, item.observations, windows, configuration)
            for finding in findings:
                key = (name, finding["policy_id"])
                hits[key].append(cutoff.isoformat())
                if key in expected and expected[key].matches(cutoff, finding):
                    matches[key].append(cutoff.isoformat())
            for entry in suppressions:
                suppressed[entry.policy_id, entry.reason_code] += 1
                cohort_suppressions[groups[name], entry.reason_code] += 1

    true_positives = set(matches)
    false_positives = set(hits) - true_positives
    false_negatives = set(expected) - true_positives

    def counts(policy=None):
        def tally(result):
            return sum(rule == policy or policy is None for _, rule in result)
        tp, fp, fn = map(tally, (true_positives, false_positives, false_negatives))
        return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None}

    def pair_details(pairs, dates):
        return [{"campaign": name, "policy": policy, "scenario": groups[name], "cutoffs": dates.get((name, policy), [])}
                for name, policy in sorted(pairs)]

    return {
        "fictional": True, "policy_version": POLICY_VERSION, "configuration": configuration.snapshot(),
        "reporting_cutoffs": [day.isoformat() for day in cutoffs],
        "overall": counts(), "by_policy": {policy: counts(policy) for policy in POLICIES},
        "matched": pair_details(true_positives, matches),
        "unmatched_detections": pair_details(false_positives, hits),
        "missed_expectations": pair_details(false_negatives, hits),
        "suppressions": [{"policy": policy, "reason": reason, "count": count}
                         for (policy, reason), count in sorted(suppressed.items())],
        "cohort_suppressions": [{"scenario": group, "reason": reason, "count": count}
                                for (group, reason), count in sorted(cohort_suppressions.items())],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the JSON report to this file.")
    args = parser.parse_args()
    with SessionLocal() as db:
        payload = json.dumps(evaluate_seed(db), indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
