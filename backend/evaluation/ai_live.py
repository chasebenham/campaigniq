"""Run at most three fictional campaign analyses with one optional retry each."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx2 as httpx

SCENARIOS = {
    "CPA deterioration": ("D-01", "New Customer Acquisition"),
    "Potential scaling": ("D-05", "All-Weather Gear Shopping"),
    "Data quality": ("D-06", "Alpine Collection Video"),
}
RETRYABLE = {"AI_PROVIDER_TIMEOUT", "AI_PROVIDER_UNAVAILABLE", "AI_INVALID_OUTPUT"}
ACCOUNT_ERRORS = {"AI_PROVIDER_AUTH", "AI_PROVIDER_PERMISSION", "AI_PROVIDER_MODEL_UNAVAILABLE", "AI_PROVIDER_QUOTA"}


def fictional(finding: dict) -> bool:
    return all(period["fictional_days"] == period["observed_days"]
               for period in (finding["current_evidence"], finding["baseline_evidence"]) if period)


def history(client: httpx.Client, finding_id: int) -> list[dict]:
    result = client.get(f"insights/{finding_id}/analyses", params={"page_size": 5})
    result.raise_for_status()
    return result.json()["items"]


def run(client: httpx.Client) -> dict:
    configuration = client.get("ai/status")
    configuration.raise_for_status()
    if configuration.json()["provider_max_attempts"] != 1:
        raise SystemExit("Start the API with AI_PROVIDER_MAX_ATTEMPTS=1 to bound the smoke test.")
    check = client.post("ai/status/check")
    check.raise_for_status()
    provider = check.json()
    report = {"model": provider["model"], "access": provider["provider_status"],
              "provider_error": provider["provider_error_code"], "scenarios": {}}
    if provider["provider_status"] != "ACCESSIBLE":
        return report

    for name, (policy, preferred) in SCENARIOS.items():
        response = client.get("insights", params={"policy_id": policy, "scope": "current", "page_size": 100})
        response.raise_for_status()
        options = [entry for entry in response.json()["items"] if fictional(entry)]
        ordered = sorted(options, key=lambda item: item["campaign_snapshot"]["campaign_name"] != preferred)
        if not ordered:
            report["scenarios"][name] = {"status": "NO_ELIGIBLE_FICTIONAL_FINDING"}
            continue
        finding = ordered[0]
        finding_id = finding["id"]
        entry = report["scenarios"][name] = {
            "finding_id": finding_id, "run_id": finding["run_id"], "campaign": finding["campaign_snapshot"]["campaign_name"],
            "attempts": [], "human_review": "PENDING",
        }
        for attempt in range(2):
            before = {record["id"] for record in history(client, finding_id)}
            result = client.post(f"insights/{finding_id}/analyses")
            if result.status_code in {200, 201, 202}:
                record = result.json()
                entry["status"] = record["status"]
                entry["attempts"].append({"http": result.status_code, "analysis": record})
                break
            error = result.json().get("error", {}).get("code", "UNKNOWN_ERROR")
            records = [record for record in history(client, finding_id) if record["id"] not in before]
            entry["attempts"].append({"http": result.status_code, "error": error, "analysis": records[0] if records else None})
            entry["status"] = error
            if error in ACCOUNT_ERRORS:
                return report
            if error not in RETRYABLE or attempt == 1:
                break
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8118/api/v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize the bounded paid requests.")
    args = parser.parse_args()
    url = urlsplit(args.api)
    if not args.execute or url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Use --execute and a local loopback API URL.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new writable report before issuing any potentially billable request.
    with args.output.open("x", encoding="utf-8") as target:
        with httpx.Client(base_url=args.api.rstrip("/") + "/", timeout=65, trust_env=False) as client:
            report = run(client)
        target.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"model": report["model"], "access": report["access"],
                      "results": {name: item["status"] for name, item in report["scenarios"].items()}}))


if __name__ == "__main__":
    main()
