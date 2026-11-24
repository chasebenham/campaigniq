"""Run one explicitly selected fictional campaign analysis without retries."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx2 as httpx

from app.ai_contract import SCHEMA_VERSION

SCENARIOS = {
    "D-01": "New Customer Acquisition", "D-05": "All-Weather Gear Shopping", "D-06": "Alpine Collection Video",
}


def fictional(finding: dict) -> bool:
    return all(period["fictional_days"] == period["observed_days"]
               for period in (finding["current_evidence"], finding["baseline_evidence"]) if period)


def history(client: httpx.Client, finding_id: int) -> list[dict]:
    result = client.get(f"insights/{finding_id}/analyses", params={"page_size": 5})
    result.raise_for_status()
    return result.json()["items"]


def selected_finding(client: httpx.Client, policy: str) -> dict:
    response = client.get("insights", params={"policy_id": policy, "scope": "current", "page_size": 100})
    response.raise_for_status()
    for item in response.json()["items"]:
        if fictional(item) and item["campaign_snapshot"]["campaign_name"] == SCENARIOS[policy]:
            return item
    raise SystemExit(f"The exact fictional {policy} scenario is unavailable among current findings.")


def run(client: httpx.Client, policy: str) -> dict:
    configuration = client.get("ai/status")
    configuration.raise_for_status()
    provider = configuration.json()
    if provider["provider_max_attempts"] != 1:
        raise SystemExit("Start the API with AI_PROVIDER_MAX_ATTEMPTS=1 to bound the smoke test.")
    if not provider["enabled"]:
        raise SystemExit("AI must be enabled and configured for live verification.")
    if policy != "D-01":
        cpa = selected_finding(client, "D-01")
        if not any(item["is_current"] and item["status"] == "COMPLETED" and item["schema_version"] == SCHEMA_VERSION
                   for item in history(client, cpa["id"])):
            raise SystemExit("The CPA case must pass and persist before later scenarios.")
    finding = selected_finding(client, policy)
    finding_id = finding["id"]
    previous = history(client, finding_id)
    if any(item["schema_version"] == SCHEMA_VERSION for item in previous):
        raise SystemExit("This scenario already has an attempt under the current schema. No request was made.")
    result = client.post(f"insights/{finding_id}/analyses")
    if result.status_code in {200, 201, 202}:
        record, error = result.json(), None
    else:
        error = result.json().get("error", {}).get("code", "UNKNOWN_ERROR")
        old_ids = {item["id"] for item in previous}
        record = next((item for item in history(client, finding_id) if item["id"] not in old_ids), None)
    return {"model": provider["model"], "policy": policy, "campaign": SCENARIOS[policy], "finding_id": finding_id,
            "http": result.status_code, "status": record["status"] if record else error,
            "error": error, "analysis": record, "human_review": "PENDING"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8118/api/v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize the bounded paid requests.")
    args = parser.parse_args()
    url = urlsplit(args.api)
    if not args.execute or url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Use --execute and a local loopback API URL.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new writable report before issuing any potentially billable request.
    with args.output.open("x", encoding="utf-8") as target:
        with httpx.Client(base_url=args.api.rstrip("/") + "/", timeout=65, trust_env=False) as client:
            report = run(client, args.scenario)
        target.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("model", "policy", "http", "status", "error")}))


if __name__ == "__main__":
    main()
