"""Synthetic responses built against exported fictional evidence, not recovered provider output."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_contract import cited_paths, provider_payload, provider_schema, validate_output
from app.ai_diagnostics import OutputRejection
from app.ai_models import AIAnalysis
from app.ai_provider import OpenAIProvider
from test_ai import PATH, ProviderStub, ai_dependencies, create_finding, mock_provider_transport, sample_output, sdk_response

import httpx2 as httpx

SNAPSHOTS = {item["finding_id"]: item for item in json.loads(
    (Path(__file__).parent / "fixtures/ai_persisted_evidence.json").read_text(encoding="utf-8")
)}

CITATIONS = {
    3: ["current.metrics.cpa", "baseline.metrics.cpa", "current.metrics.cpc", "baseline.metrics.cpc",
        "current.metrics.purchase_cvr", "baseline.metrics.purchase_cvr", "observations.cpa_change_pct"],
    6: ["current.metrics.roas", "targets.target_roas", "observations.roas_change_pct"],
    16: ["related_quality_flags.0.dates.0", "baseline.observed_days", "baseline.expected_days"],
}


def valid_response(finding_id: int) -> dict:
    values = {
        3: [("current.metrics.cpa", "$58.90"), ("baseline.metrics.cpa", "$49.02"),
            ("current.metrics.purchase_cvr", "3.49%"), ("observations.cpa_change_pct", "20.15%")],
        6: [("current.metrics.roas", "10.08×"), ("targets.target_roas", "4.00x")],
        16: [("baseline.observed_days", "2"), ("baseline.expected_days", "7")],
    }
    response = sample_output(
        finding_id, evidence_references=CITATIONS[finding_id],
        numeric_claims=[{"reference": reference, "value": value} for reference, value in values[finding_id]],
    )
    if finding_id == 3:
        response["executive_summary"] = "Higher click costs and lower purchase CVR both contribute to higher CPA."
    if finding_id == 6:
        response.update(
            executive_summary="Average attributed ROAS exceeded target. Marginal returns remain uncertain.",
            recommended_action_type="TEST", experiment_hypothesis="A limited spend test may preserve efficiency at the margin.",
            proposed_experiment={
                "design": "Compare a treatment with a matched holdout.",
                "audience_or_scope": "Eligible comparable campaign inventory.",
                "duration": "Wait for the pre-registered minimum purchase volume and attribution maturity.",
                "guardrails": "Stop if the spending cap or cost threshold is breached.",
                "decision_rule": "Compare marginal attributed return and cost with the holdout.",
                "proposed_change": "Increase spend within a pre-registered cap in the treatment.",
                "comparison": "Keep campaign spend unchanged in the comparator.",
                "guardrail_metrics": ["Spend", "Attributed CPA"],
            }, primary_success_metric="Marginal attributed ROAS", secondary_metrics=["Attributed CPA"],
        )
    if finding_id == 16:
        response.update(
            executive_summary="Missing baseline days block a reliable comparison.",
            recommended_action="Reconcile the missing reports against the platform and rerun detection.",
            possible_explanations=["An export gap could have omitted the affected dates.", "A delivery interruption may require source confirmation."],
            action_rationale="Restore reporting coverage before interpreting performance changes.",
        )
    return response


@pytest.mark.parametrize("finding_id", [3, 6, 16])
def test_offline_representative_responses_match_persisted_fictional_evidence(finding_id):
    snapshot = SNAPSHOTS[finding_id]
    output = validate_output(valid_response(finding_id), snapshot)
    payload = provider_payload(snapshot)
    fields = provider_schema(snapshot)["properties"]
    assert fields["evidence_references"]["items"]["enum"] == payload["allowed_evidence_references"]
    assert {claim.reference for claim in output.numeric_claims} <= payload["numeric_evidence"].keys()
    assert output.model_dump() == valid_response(finding_id)


@pytest.mark.parametrize(("field", "value", "rule", "path"), [
    ("evidence_references", ["unrecognized-sensitive-text"], "UNKNOWN_REFERENCE", "/evidence_references/0"),
    ("evidence_references", ["current.metrics.cpa"], "MISSING_CORE_REFERENCES", "/evidence_references"),
    ("numeric_claims", [{"reference": "current.metrics.cpa", "value": "$58.89"}], "NUMERIC_MISMATCH", "/numeric_claims/0/value"),
    ("numeric_claims", [{"reference": "current.metrics.cpa", "value": "58.90%"}], "NUMERIC_UNIT", "/numeric_claims/0/value"),
    ("numeric_claims", [{"reference": "reporting_definitions.0.date_basis", "value": "100"}], "NUMERIC_REFERENCE", "/numeric_claims/0/reference"),
    ("executive_summary", "I inspected the landing page and confirmed the cause.", "ASSET_INSPECTION", "/executive_summary"),
    ("executive_summary", "The landing page caused the decline.", "ASSERTED_CAUSE", "/executive_summary"),
    ("executive_summary", "The decline was statistically significant.", "CLAIMED_SIGNIFICANCE", "/executive_summary"),
    ("executive_summary", "This saved $10,000 in incremental revenue.", "UNBOUND_PROSE_NUMBER", "/executive_summary"),
])
def test_rejected_response_identifies_rule_and_field(field, value, rule, path):
    raw = valid_response(3)
    raw[field] = value
    with pytest.raises(OutputRejection) as result:
        validate_output(raw, SNAPSHOTS[3])
    assert (result.value.diagnostic.rule, result.value.diagnostic.field_path) == (rule, path)
    assert "unrecognized-sensitive-text" not in str(result.value.diagnostic)


def test_schema_errors_report_required_field_without_raw_content():
    raw = valid_response(3)
    del raw["action_rationale"]
    raw["private-account-data"] = "sensitive free text"
    with pytest.raises(OutputRejection) as result:
        validate_output(raw, SNAPSHOTS[3])
    diagnostic = result.value.diagnostic
    assert diagnostic.category == "SCHEMA" and diagnostic.field_path == "/action_rationale"
    assert {"field_path": "/<redacted>", "type": "extra_forbidden"} in diagnostic.actual["errors"]
    assert "sensitive" not in str(diagnostic) and "private-account-data" not in str(diagnostic)


def test_quality_count_is_a_grounded_citation_without_a_second_listing():
    raw = valid_response(16)
    raw["evidence_references"].remove("baseline.expected_days")
    output = validate_output(raw, SNAPSHOTS[16])
    assert output.model_dump() == raw
    assert cited_paths(raw).count("baseline.expected_days") == 1
    raw["numeric_claims"].append(raw["numeric_claims"][1])
    with pytest.raises(OutputRejection, match="DUPLICATE_NUMERIC_REFERENCE"):
        validate_output(raw, SNAPSHOTS[16])


def test_numeric_only_citation_resolves_to_persisted_value_in_api_history(client, ai_dependencies, csv_file, submit):
    finding = create_finding(client, csv_file, submit)
    raw = sample_output(finding["id"], numeric_claims=[{"reference": "current.metrics.cpa", "value": "$20.00"}])
    raw["evidence_references"].remove("current.metrics.cpa")
    ai_dependencies(provider=ProviderStub(output=raw))
    path = f"{PATH}/insights/{finding['id']}/analyses"
    reply = client.post(path)
    assert reply.status_code == 201, reply.text
    analysis = client.get(path).json()["items"][0]
    assert "current.metrics.cpa" not in analysis["structured_output"]["evidence_references"]
    assert any(item["path"] == "current.metrics.cpa" for item in analysis["evidence_references"])


def test_missing_optional_cpa_measurement_has_no_required_citation():
    snapshot = deepcopy(SNAPSHOTS[3])
    snapshot["evidence"]["baseline"]["metrics"]["purchase_cvr"] = None
    raw = valid_response(3)
    raw["evidence_references"] = [path for path in raw["evidence_references"] if path != "baseline.metrics.purchase_cvr"]
    assert validate_output(raw, snapshot).finding_id == 3


@pytest.mark.postgres
def test_incomplete_provider_response_is_persisted_and_diagnostic_is_private(
    postgres, client_for, ai_dependencies, csv_file, submit, monkeypatch,
):
    engine, _ = postgres
    calls = []

    def reply(request):
        calls.append(request.method)
        body = sdk_response({}).json()
        body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        body["output"][0]["content"][0]["text"] = "private incomplete text"
        return httpx.Response(200, json=body)

    mock_provider_transport(monkeypatch, reply)
    ai_dependencies(provider=OpenAIProvider())
    with client_for(engine) as client:
        finding = create_finding(client, csv_file, submit)
        response = client.post(f"{PATH}/insights/{finding['id']}/analyses")
        assert response.status_code == 502 and calls == ["POST"]
        history = client.get(f"{PATH}/insights/{finding['id']}/analyses").json()["items"]
        assert history[0]["provider_usage"]["total_tokens"] == 300 and "validation_diagnostic" not in history[0]
        assert "private incomplete text" not in response.text
    with Session(engine) as db:
        record = db.scalar(select(AIAnalysis))
        artifact = record.validation_diagnostic
        assert record.status == "FAILED" and record.structured_output is None
        assert artifact["rule"] == "RESPONSE_INCOMPLETE" and artifact["provider_response_status"] == "incomplete"
        assert artifact["schema_version"] == record.schema_version and artifact["evidence_fingerprint"] == record.evidence_fingerprint
        assert artifact["analysis_attempt_id"] == record.id and "private incomplete text" not in str(artifact)
