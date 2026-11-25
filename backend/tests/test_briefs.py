import json
from datetime import date, datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai_config import AISettings, get_ai_settings
from app.ai_contract import build_snapshot
from app.ai_models import AIAnalysis
from app.ai_provider import ProviderFailure, StructuredResponse, get_ai_provider
from app.brief_models import BriefSummaryAttempt, StrategyBriefVersion
from app.briefs.synthesis import validate_synthesis
from app.briefs.commentary import FIELDS
from app.detection import fingerprint, source_version
from app.detection_models import DetectionFinding, DetectionRun
from app.main import app
from app.models import Campaign, DailyCampaignPerformance
from app.seed import seed

BASE = "/api/v1/strategy-briefs"
PERIOD = {"start": "2026-09-01", "end": "2026-09-07"}
STAMP = datetime(2026, 9, 20, tzinfo=timezone.utc)


def make_draft(**selection):
    return {"title": "September • Fictional leadership review", "sources": {"period": PERIOD, **selection},
            "narrative": {"commentary": "Review reporting coverage before increasing spend."}}


def save(client, draft, report=None):
    path = f"{BASE}/{report}" if report else BASE
    preview = client.post(f"{path}/preview", json=draft)
    assert preview.status_code == 200, preview.text
    body = {**draft, "evidence_fingerprint": preview.json()["evidence_fingerprint"]}
    response = client.put(path, json=body) if report else client.post(path, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def reporting_data(client, csv_file, submit, *, other_method="LAST_CLICK"):
    rows = [
        dict(date="2026-09-01", campaign_id="trail", campaign_name="Trail Search",
             spend="50", attributed_purchases="2", attributed_purchase_value="160"),
        dict(date="2026-09-01", campaign_id="gear", campaign_name="Gear Social", platform="META_ADS",
             spend="100", attributed_purchases="1", attributed_purchase_value="240", attribution_method=other_method),
    ]
    assert submit(client, csv_file(*rows)).status_code == 201


def overview(document):
    return next(section["blocks"][0] for section in document["sections"]
                if section["title"] == "Marketing Performance Overview")


def test_report_weighted_metrics_and_frozen_export(client, csv_file, submit):
    reporting_data(client, csv_file, submit)
    draft = make_draft()
    saved = save(client, draft)
    table = {row[0]: row[1:] for row in overview(saved["document"])["tables"][0]["rows"]}
    assert table["Spend"] == ["$150.00", "$50.00", "$100.00"]
    assert table["CPA"] == ["$50.00", "$25.00", "$100.00"]
    assert table["ROAS"] == ["2.67x", "3.20x", "2.40x"]
    assert table["Attributed purchases"] == ["3", "2", "1"]
    assert table["CTR"] == ["10.00%", "10.00%", "10.00%"]
    assert any("12 of 14" in warning for warning in saved["warnings"])
    assert any("may overlap" in warning for warning in saved["warnings"])
    assert not any("Budget Scenario Analysis" == section["title"] for section in saved["document"]["sections"])
    path = f"{BASE}/{saved['brief_id']}/export/pdf"
    assert client.get(path).status_code == 422
    pdf = client.get(path, params={"version": 1})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "september-fictional-leadership-review-v1.pdf" in pdf.headers["content-disposition"]
    pages = PdfReader(BytesIO(pdf.content)).pages
    text = " ".join(page.extract_text() for page in pages)
    assert "$150.00" in text and "2.67x" in text and "Review reporting coverage" in text
    assert all(float(page.mediabox.width) == 612 and float(page.mediabox.height) == 792 for page in pages)


def test_unknown_or_mixed_context_withholds_portfolio_conversions(client, csv_file, submit):
    reporting_data(client, csv_file, submit, other_method="LINEAR")
    data = client.post(f"{BASE}/preview", json=make_draft()).json()
    table = {row[0]: row[1:] for row in overview(data["document"])["tables"][0]["rows"]}
    assert table["Spend"] == ["$150.00", "$50.00", "$100.00"]
    assert table["ROAS"] == ["Unavailable", "3.20x", "2.40x"]
    assert any("definitions differ" in warning for warning in data["warnings"])


def findings_with_analysis(engine):
    current = {"start": "2026-09-01", "end": "2026-09-07", "calendar_days": 7, "observed_days": 7,
               "expected_days": 7, "complete": True, "fictional_days": 0, "missing_dates": [],
               "metrics": {"spend": "70", "attributed_purchases": "2", "roas": "2.40", "cpa": "35.00", "cpc": "0.70"}}
    baseline = {**current, "start": "2026-08-25", "end": "2026-08-31",
                "metrics": dict(current["metrics"], spend="50", cpa="25.00", cpc="0.50")}
    with Session(engine) as db, db.begin():
        campaign = db.scalar(select(Campaign).where(Campaign.external_campaign_id == "trail"))
        run = DetectionRun(started_at=STAMP, finished_at=STAMP, evaluation_date=STAMP.date(), status="COMPLETED",
                           windows={"current": PERIOD}, policy_version="1.0.0", configuration={}, source_version=source_version(db),
                           input_fingerprint="7" * 64, campaign_count=2, finding_count=2, suppression_count=0, errors=[])
        db.add(run)
        db.flush()
        ids = []
        for policy in ["D-01", "D-02"]:
            row = DetectionFinding(
                run_id=run.id, campaign_id=campaign.id, policy_id=policy, policy_version="1.0.0",
                category="PERFORMANCE_RISK", severity="HIGH", summary="Observed efficiency decline",
                classification_reason="The observed deviation met the configured rule.",
                current_evidence=current, baseline_evidence=baseline, thresholds={"cpa_increase_pct": "20"},
                campaign_snapshot={"campaign_name": campaign.campaign_name, "platform": campaign.platform, "objective": "PURCHASES",
                                   "target_cpa": "25.00", "target_roas": "3.00"},
                observations={"cpa_change_pct": "40"}, reporting_context=[], evidence_quality="SUFFICIENT",
                data_quality_flags=[], limitations=["The observed change does not establish causality."],
                fingerprint=policy * 12, spend_exposure=70, magnitude=40, created_at=STAMP,
            )
            db.add(row)
            db.flush()
            ids.append(row.id)
            if policy == "D-01":
                snapshot = build_snapshot(row)
                analysis = AIAnalysis(
                    finding_id=row.id, status="COMPLETED", model="gpt-6-luna", prompt_version="fixture",
                    schema_version="fixture", created_at=STAMP, finished_at=STAMP,
                    evidence_fingerprint=fingerprint(snapshot), evidence_snapshot=snapshot,
                    structured_output={
                        "finding_id": row.id, "executive_summary": "Observed acquisition efficiency fell.",
                        "business_impact_assessment": "Acquisition may require greater spend.",
                        "evidence_references": ["current.metrics.cpa"],
                        "possible_explanations": ["Auction conditions may have changed."],
                        "missing_information": ["Review delivery breakdown."], "recommended_action_type": "INVESTIGATE",
                        "recommended_action": "Inspect auction mix.", "experiment_hypothesis": "Mix may affect acquisition cost.",
                        "proposed_experiment": {"design": "Compare segments.", "audience_or_scope": "Search traffic", "duration": "Until evidence is sufficient",
                                                "guardrails": "Monitor spend.", "decision_rule": "Review changes in cost."},
                        "primary_success_metric": "Observed CPA", "secondary_metrics": ["CTR"],
                        "risks_and_limitations": ["No causal evidence."], "confidence_rationale": "Observed attribution only.",
                    },
                )
                db.add(analysis)
                db.flush()
                analysis_id = analysis.id
        return ids, analysis_id


def test_finding_and_analysis_selection_and_stale_revision(client, memory_engine, csv_file, submit):
    reporting_data(client, csv_file, submit)
    ids, analysis = findings_with_analysis(memory_engine)
    options = client.get(f"{BASE}/sources", params=PERIOD).json()
    assert options["suggested_run_id"] and options["findings"]["total"] == 2
    assert options["findings"]["items"][0]["analyses"][0]["id"] == analysis
    assert client.post(f"{BASE}/preview", json=make_draft(findings=[{"finding_id": ids[1], "analysis_id": analysis}])).json()["error"]["code"] == "INVALID_ANALYSIS"
    assert client.post(f"{BASE}/preview", json=make_draft(findings=[{"finding_id": 999}])).json()["error"]["code"] == "INVALID_FINDING"
    duplicate = {"finding_id": ids[0]}
    assert client.post(f"{BASE}/preview", json=make_draft(findings=[duplicate, duplicate])).status_code == 422
    selected = [{"finding_id": ids[0], "analysis_id": analysis}, {"finding_id": ids[1]}]
    draft = make_draft(findings=selected)
    outside = {**draft, "sources": {"findings": selected, "period": {**PERIOD, "end": "2026-09-06"}}}
    assert client.post(f"{BASE}/preview", json=outside).json()["error"]["code"] == "FINDING_OUTSIDE_PERIOD"
    saved = save(client, draft)
    key = saved["brief_id"]
    assert any("share a campaign" in text for text in saved["warnings"])
    assert "Inspect auction mix." in json.dumps(saved["document"])
    assert "Proposed Marketing Experiments" in json.dumps(saved["document"])
    assert submit(client, csv_file(dict(date="2026-09-02", campaign_id="trail", campaign_name="Trail Search"))).status_code == 201
    prior = client.get(f"{BASE}/{key}").json()
    assert prior["freshness"] == "STALE" and prior["document"] == saved["document"]
    assert client.post(f"{BASE}/preview", json=draft).json()["error"]["code"] == "HISTORICAL_SOURCE"
    revised = save(client, {**draft, "base_version": 1, "narrative": {"commentary": "Preserve the original measurements."}}, key)
    assert revised["version"] == 2 and revised["freshness"] == "STALE"
    assert overview(revised["document"]) == overview(saved["document"])
    assert client.get(f"{BASE}/{key}/versions/1").json()["document"] == saved["document"]
    assert client.get(f"{BASE}/{key}/versions").json()["total"] == 2
    assert client.put(f"{BASE}/{key}", json={**draft, "base_version": 1, "evidence_fingerprint": saved["evidence_fingerprint"]}).status_code == 409
    refreshed = save(client, {**draft, "base_version": 2, "refresh_evidence": True, "allow_historical": True}, key)
    assert refreshed["version"] == 3 and refreshed["freshness"] == "CURRENT"
    assert refreshed["evidence_fingerprint"] != saved["evidence_fingerprint"]
    assert any("historical or stale" in message for message in refreshed["warnings"])


@pytest.fixture
def summary_provider():
    class Provider:
        replies = []
        calls = 0

        def structured(self, settings, **request):
            self.calls += 1
            assert not request["payload"].get("narrative")
            if not self.replies:
                raise AssertionError("Unexpected provider call")
            action = self.replies.pop(0)
            if isinstance(action, Exception):
                raise action
            return action(request) if callable(action) else action
    provider = Provider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_ai_settings] = lambda: AISettings(ai_analysis_enabled=True, openai_api_key="test-placeholder")
    yield provider
    app.dependency_overrides.pop(get_ai_provider, None)
    app.dependency_overrides.pop(get_ai_settings, None)


def valid_response():
    return StructuredResponse(json.dumps({
        "summary": "Prioritize reviewing the available performance evidence and resolve gaps before changing media spend.",
        "references": ["performance.overview", "performance.coverage"],
    }), {"input_tokens": 100, "output_tokens": 30}, "completed")


def test_ai_summary_gating_numeric_reference_errors_cache_and_authorship(client, memory_engine, summary_provider):
    provider = summary_provider
    version = save(client, make_draft())
    root = f"{BASE}/{version['brief_id']}"
    path = f"{root}/generate-summary"
    assert provider.calls == 0
    for settings, code in [
        (AISettings(ai_analysis_enabled=False), "AI_DISABLED"),
        (AISettings(ai_analysis_enabled=True, openai_api_key=""), "AI_MISSING_API_KEY"),
    ]:
        app.dependency_overrides[get_ai_settings] = lambda: settings
        assert client.post(path, json={"version": 1}).json()["error"]["code"] == code
    app.dependency_overrides[get_ai_settings] = lambda: AISettings(ai_analysis_enabled=True, openai_api_key="test-placeholder")
    provider.replies.extend([ProviderFailure("AI_PROVIDER_TIMEOUT", "OpenAI timed out.", 504), valid_response()])
    assert client.post(path, json={"version": 1}).status_code == 504
    assert client.get(root).json()["generation"]["status"] == "FAILED"
    accepted = client.post(path, json={"version": 1}).json()
    assert accepted["status"] == "COMPLETED" and accepted["usage"]["output_tokens"] == 30
    assert client.post(path, json={"version": 1}).json()["id"] == accepted["id"]
    assert provider.calls == 2
    draft = {**make_draft(), "base_version": 1, "summary_attempt_id": accepted["id"],
             "narrative": {"executive_summary": accepted["text"] + " Leadership review is pending."}}
    new = save(client, draft, version["brief_id"])
    assert "Management-edited AI summary" in json.dumps(new["document"])
    assert client.get(f"{root}/versions/1").json()["document"] == version["document"]
    assert client.post(path, json={"version": 1}).status_code == 409
    with Session(memory_engine) as db:
        assert len(list(db.scalars(select(BriefSummaryAttempt)))) == 2


@pytest.mark.parametrize("text,refs,error", [
    ("Review verified observations and reconcile the campaign records.", ["missing"], "invalid evidence"),
    ("Acquisition spend was $300 before stabilization.", ["performance.overview"], "numerical claim"),
    ("Acquisition spend fell by twenty percent.", ["performance.overview"], "numerical claim"),
    ("The landing page caused the observed decline in performance.", ["performance.overview"], "unsupported causal"),
])
def test_structured_output_fails_closed(text, refs, error):
    with pytest.raises(ValueError, match=error):
        validate_synthesis(json.dumps({"summary": text, "references": refs}), {"performance.overview": {}})
    with pytest.raises(ValueError, match="structure"):
        validate_synthesis('{"summary":"missing reference field"}', {})


def test_ai_response_is_stale_after_concurrent_revision(client, summary_provider):
    first = save(client, make_draft())
    key = first["brief_id"]

    def revise_while_away(_):
        save(client, {**make_draft(), "base_version": 1, "narrative": {"commentary": "New decision"}}, key)
        return valid_response()

    summary_provider.replies.append(revise_while_away)
    response = client.post(f"{BASE}/{key}/generate-summary", json={"version": 1})
    assert response.status_code == 200
    assert response.json()["status"] == "STALE" and response.json()["text"] is None
    assert client.get(f"{BASE}/{key}").json()["version"] == 2


def test_save_rejects_changed_source_after_preview(client, csv_file, submit):
    draft = make_draft()
    preview = client.post(f"{BASE}/preview", json=draft).json()
    reporting_data(client, csv_file, submit)
    response = client.post(BASE, json={**draft, "evidence_fingerprint": preview["evidence_fingerprint"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "EVIDENCE_CHANGED"
    assert client.get(BASE).json()["total"] == 0


def test_postgres_report_budget_reopen_and_version_exports(postgres, client_for, csv_file, submit):
    engine, _ = postgres
    with Session(engine) as db, db.begin():
        assert seed(db)[0] == 16
    with client_for(engine) as client:
        reference = {"start": "2026-09-01", "end": "2026-09-28"}
        settings = client.get("/api/v1/budget-lab/assumptions").json()
        plan = {
            "name": "Fictional budget attachment", "total_budget": "2000.00", "mode": "DOLLARS",
            "campaign_ids": [1, 2], "reference": reference, "planning": settings["planning"],
            "allocations": [{"campaign_id": key, "value": "1000.00"} for key in (1, 2)], "assumptions": settings["assumptions"],
        }
        calc = client.post("/api/v1/budget-lab/calculate", json=plan)
        assert calc.status_code == 200, calc.text
        budget = client.post("/api/v1/budget-lab/scenarios", json={"plan": plan, "evidence_fingerprint": calc.json()["evidence_fingerprint"]})
        assert budget.status_code == 201, budget.text
        draft = make_draft(budget_id=budget.json()["id"])
        first = save(client, draft)
        assert "Fictional budget attachment" in json.dumps(first["document"])
        assert "Conservative" in json.dumps(first["document"])
        assert client.post(f"{BASE}/preview", json=make_draft(budget_id=999)).json()["error"]["code"] == "INVALID_BUDGET"
    engine.dispose()
    with client_for(engine) as client:
        key = first["brief_id"]
        reopened = client.get(f"{BASE}/{key}").json()
        assert reopened == first
        assert submit(client, csv_file(dict(date="2026-09-02", campaign_id="late", campaign_name="Fictional delayed campaign"))).status_code == 201
        assert client.get(f"{BASE}/{key}").json()["freshness"] == "STALE"
        revised = save(client, {**draft, "base_version": 1, "narrative": {"commentary": "Compare the underlying scenarios before committing."}}, key)
        assert revised["freshness"] == "STALE" and revised["version"] == 2
        for version, snippet in [(1, "Review reporting coverage"), (2, "Compare the underlying scenarios")]:
            response = client.get(f"{BASE}/{key}/export/pdf", params={"version": version})
            exported = " ".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
            assert snippet in exported and "$2,000.00" in exported
    with Session(engine) as db:
        rows = list(db.scalars(select(StrategyBriefVersion).order_by(StrategyBriefVersion.version)))
        assert len(rows) == 2 and rows[0].evidence == rows[1].evidence
    with engine.begin() as db:
        db.execute(update(DailyCampaignPerformance).where(
            DailyCampaignPerformance.campaign_id == 1, DailyCampaignPerformance.report_date == date(2026, 9, 25),
        ).values(spend=789))
    with client_for(engine) as client:
        declined = client.post(f"{BASE}/preview", json=draft)
        assert declined.status_code == 409 and declined.json()["error"]["code"] == "HISTORICAL_SOURCE"
        historical = save(client, {**draft, "allow_historical": True})
        assert any("stale reference evidence" in item for item in historical["warnings"])
    with Session(engine) as db:
        rows = list(db.scalars(select(StrategyBriefVersion).order_by(StrategyBriefVersion.id)))
        assert rows[0].evidence["budget"]["result"] == rows[2].evidence["budget"]["result"]


COMMENTARY = f"{BASE}/draft-commentary"
PHRASES = {
    "executive_summary": "Observed spend was [[performance.overview.spend]]. Reconcile reporting gaps before making broad claims about acquisition performance.",
    "recommendations": "Reconcile the affected reporting sources before changing media allocation. Review the verified evidence alongside platform limitations.",
    "commentary": "Management should weigh the usefulness of reported results against the uncertainty from incomplete measurement.",
    "experiment": "The available comparisons do not establish a suitable intervention. Inspect attribution coverage and delivery records before designing a test.",
    "next_decisions": "Review campaign reporting with the operational team. Establish what evidence is needed before approving a test.",
}


def commentary_request(target="all", **extra):
    return {"request_id": str(uuid4()), "target": target, "sources": {"period": PERIOD}, **extra}


def commentary_response(target="all", *, output_override=None):
    result = {}
    for name in FIELDS if target == "all" else (target,):
        field = {"text": PHRASES[name], "references": ["performance.overview"], "numeric_claims": []}
        if name == "executive_summary":
            field["numeric_claims"] = [{"reference": "performance.overview.spend", "value": "$150.00"}]
        if name == "experiment":
            field["purpose"] = "further_investigation"
        result[name] = {**field, **(output_override or {})}
    return StructuredResponse(json.dumps(result), {"input_tokens": 200, "output_tokens": 100}, "completed")


@pytest.mark.parametrize("field", FIELDS)
def test_commentary_individual_requests(client, csv_file, submit, summary_provider, field):
    reporting_data(client, csv_file, submit)
    summary_provider.replies.append(commentary_response(field))
    response = client.post(COMMENTARY, json=commentary_request(field))
    assert response.status_code == 200, response.text
    out = response.json()
    assert set(out["fields"]) == {field} == set(out["provenance"])
    assert "[[" not in out["fields"][field]
    meta = out["provenance"][field]
    assert meta["usage"]["output_tokens"] == 100 and meta["authorship"] == "AI_GENERATED"
    assert meta["evidence_fingerprint"] and meta["prompt_version"] and meta["generated_at"]
    assert client.get(BASE).json()["total"] == 0


def test_commentary_batch_replay_and_saved_provenance(postgres, client_for, csv_file, submit, summary_provider):
    engine, _ = postgres
    with client_for(engine) as client:
        reporting_data(client, csv_file, submit)
        body = commentary_request()
        summary_provider.replies.append(commentary_response())
        draft = client.post(COMMENTARY, json=body).json()
        assert draft == client.post(COMMENTARY, json=body).json()
        assert summary_provider.calls == 1 and set(draft["fields"]) == set(FIELDS)
        versions = make_draft()
        versions["narrative"] = {**draft["fields"], "commentary": "Keep the team's manual assessment."}
        versions["commentary_attempt_ids"] = {field: meta["id"] for field, meta in draft["provenance"].items()}
        saved = save(client, versions)
        key = saved["brief_id"]
        assert saved["draft"]["narrative"]["commentary"] == "Keep the team's manual assessment."
        assert saved["commentary_provenance"]["commentary"]["authorship"] == "AI_EDITED_BY_MANAGEMENT"
        assert saved["commentary_provenance"]["executive_summary"]["authorship"] == "AI_GENERATED"
        assert saved["generation"] is None
        pdf = client.get(f"{BASE}/{key}/export/pdf?version=1")
        text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "$150.00" in text and "Keep the team's manual assessment." in text
        assert "Management-edited AI draft" in text
    engine.dispose()
    with client_for(engine) as client:
        assert client.get(f"{BASE}/{key}").json() == saved
        new_selection = {**versions, "base_version": 1, "sources": {"period": {**PERIOD, "end": "2026-09-08"}}}
        revision = save(client, new_selection, key)
        assert revision["commentary_provenance"]["commentary"]["stale"] is True
        assert revision["draft"]["narrative"] == saved["draft"]["narrative"]
        assert client.get(f"{BASE}/{key}/versions/1").json()["commentary_provenance"] == saved["commentary_provenance"]


@pytest.mark.parametrize("override,rule", [
    ({"references": ["faked.reference"]}, "INVALID_REFERENCES"),
    ({"numeric_claims": [{"reference": "performance.overview.spend", "value": "151"}]}, "NUMERIC_MISMATCH"),
    ({"numeric_claims": [{"reference": "performance.overview.spend", "value": "150%"}]}, "NUMERIC_UNIT"),
    ({"text": "We saved $300 in this reporting period after the test.", "numeric_claims": []}, "UNBOUND_NUMBER"),
])
def test_draft_validation_retains_safe_diagnostic(client, memory_engine, csv_file, submit, summary_provider, override, rule):
    reporting_data(client, csv_file, submit)
    summary_provider.replies.append(commentary_response("executive_summary", output_override=override))
    response = client.post(COMMENTARY, json=commentary_request("executive_summary"))
    assert response.status_code == 502 and rule in response.json()["error"]["message"]
    with Session(memory_engine) as db:
        attempt = db.scalar(select(BriefSummaryAttempt))
        assert attempt.status == "FAILED" and "fields" not in attempt.output
        assert attempt.output["diagnostic"]["rule"] == rule


def test_commentary_allows_rounded_kpi(client, csv_file, submit, summary_provider):
    reporting_data(client, csv_file, submit)
    summary_provider.replies.append(commentary_response("executive_summary", output_override={
        "text": "Observed platform-attributed ROAS was [[performance.overview.roas]] across the reported campaigns.",
        "numeric_claims": [{"reference": "performance.overview.roas", "value": "2.67x"}],
    }))
    response = client.post(COMMENTARY, json=commentary_request("executive_summary"))
    assert response.status_code == 200, response.text
    assert "2.67×" in response.json()["fields"]["executive_summary"]


def test_commentary_provider_errors_duplicate_pending_and_source_drift(client, csv_file, submit, summary_provider):
    reporting_data(client, csv_file, submit)
    for settings, code in [
        (AISettings(ai_analysis_enabled=False), "AI_DISABLED"),
        (AISettings(ai_analysis_enabled=True, openai_api_key=""), "AI_MISSING_API_KEY"),
    ]:
        app.dependency_overrides[get_ai_settings] = lambda: settings
        assert client.post(COMMENTARY, json=commentary_request()).json()["error"]["code"] == code
    app.dependency_overrides[get_ai_settings] = lambda: AISettings(ai_analysis_enabled=True, openai_api_key="test-placeholder")
    summary_provider.replies.append(ProviderFailure("AI_PROVIDER_TIMEOUT", "OpenAI timed out.", 504))
    assert client.post(COMMENTARY, json=commentary_request()).status_code == 504
    req = commentary_request("commentary")

    def change_evidence(_):
        duplicate = client.post(COMMENTARY, json=req)
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "COMMENTARY_PENDING"
        assert submit(client, csv_file(dict(date="2026-09-02", campaign_id="trail", campaign_name="Trail Search"))).status_code == 201
        return commentary_response("commentary")

    summary_provider.replies.append(change_evidence)
    changed = client.post(COMMENTARY, json=req)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "COMMENTARY_STALE"
    assert summary_provider.calls == 2


def test_commentary_uses_measurement_validation_for_blocked_evidence(client, memory_engine, csv_file, submit, summary_provider):
    reporting_data(client, csv_file, submit)
    ids, _ = findings_with_analysis(memory_engine)
    with Session(memory_engine) as db, db.begin():
        finding = db.get(DetectionFinding, ids[0])
        finding.category, finding.policy_id, finding.evidence_quality = "DATA_QUALITY", "D-06", "BLOCKED"
    sources = {"period": PERIOD, "findings": [{"finding_id": ids[0]}]}
    summary_provider.replies.append(commentary_response("experiment", output_override={"purpose": "marketing_test"}))
    rejected = client.post(COMMENTARY, json=commentary_request("experiment", sources=sources))
    assert rejected.status_code == 502 and "MEASUREMENT_FIRST" in rejected.json()["error"]["message"]
    summary_provider.replies.append(commentary_response("experiment", output_override={"purpose": "measurement_validation"}))
    accepted = client.post(COMMENTARY, json=commentary_request("experiment", sources=sources))
    assert accepted.status_code == 200, accepted.text
