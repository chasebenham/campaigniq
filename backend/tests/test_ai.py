import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_config import AISettings, get_ai_settings
from app.ai_contract import AnalysisOutput, validate_output
from app.ai_models import AIAnalysis
from app.ai_provider import OpenAIProvider, ProviderFailure, ProviderResult, get_ai_provider
from app.detection import fingerprint
from app.main import app
from evaluation.ai import evaluate_cases

PATH = "/api/v1"
ENABLED = AISettings.model_construct(ai_analysis_enabled=True, openai_api_key=SecretStr("local-test-key"),
                                    openai_model="mock-model")


def sample_output(target_id: int, **changes):
    return {
        "finding_id": target_id,
        "executive_summary": "Observed acquisition cost increased.",
        "business_impact_assessment": "The change could pressure the campaign’s acquisition budget.",
        "evidence_references": ["current.metrics.cpa", "baseline.metrics.cpa", "observations.cpa_change_pct",
                                "current.metrics.cpc", "baseline.metrics.cpc", "current.metrics.purchase_cvr", "baseline.metrics.purchase_cvr"],
        "possible_explanations": ["Traffic composition may have changed.", "Auction pressure may have increased."],
        "missing_information": ["Audience and placement breakdowns."],
        "recommended_action_type": "INVESTIGATE",
        "recommended_action": "Compare delivery and purchase credit by audience segment.",
        "action_rationale": "Breakdowns help distinguish changes in click costs from purchase efficiency.",
        "experiment_hypothesis": None,
        "proposed_experiment": None,
        "primary_success_metric": None,
        "secondary_metrics": [],
        "risks_and_limitations": ["Attribution cannot establish causality or incrementality."],
        "confidence_rationale": "The movement is measured and the cause remains uncertain.",
        "numeric_claims": [],
        **changes,
    }


def create_finding(client, csv_file, submit):
    first = date(2026, 11, 2)
    rows = [{"date": (first + timedelta(days=index)).isoformat(), "spend": "100" if index >= 7 else "60"}
            for index in range(14)]
    assert submit(client, csv_file(*rows)).status_code == 201
    assert client.post(f"{PATH}/detection/runs", json={"evaluation_date": "2026-11-23"}).status_code == 201
    return client.get(f"{PATH}/insights?policy_id=D-01").json()["items"][0]


@pytest.fixture
def ai_dependencies():
    def configure(settings=ENABLED, provider=None):
        app.dependency_overrides[get_ai_settings] = lambda: settings
        if provider is not None:
            app.dependency_overrides[get_ai_provider] = lambda: provider
    yield configure
    app.dependency_overrides.pop(get_ai_settings, None)
    app.dependency_overrides.pop(get_ai_provider, None)


class ProviderStub(OpenAIProvider):
    def __init__(self, output=None, failure=None):
        super().__init__()
        self.output = output
        self.failure = failure
        self.calls = []

    def generate(self, settings, snapshot):
        self.calls.append(snapshot)
        if self.failure:
            raise self.failure
        return ProviderResult(self.output or sample_output(snapshot["finding_id"]),
                              {"input_tokens": 350, "output_tokens": 120, "total_tokens": 470})


def test_disabled_or_unconfigured_ai_preserves_detection(client, ai_dependencies, csv_file, submit):
    provider = ProviderStub()
    for settings, reason in [
        (AISettings.model_construct(ai_analysis_enabled=False), "DISABLED"),
        (AISettings.model_construct(ai_analysis_enabled=True, openai_model="mock-model"), "MISSING_API_KEY"),
    ]:
        ai_dependencies(settings, provider)
        state = client.get(f"{PATH}/ai/status").json()
        assert not state["enabled"] and state["reason"] == reason
        assert client.post(f"{PATH}/insights/1/analyses").json()["error"]["code"] == f"AI_{reason}"
    assert create_finding(client, csv_file, submit)["policy_id"] == "D-01"
    assert not provider.calls


def test_env_file_default_model_and_environment_override(tmp_path, monkeypatch):
    for key in ("AI_ANALYSIS_ENABLED", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / ".env"
    config.write_text("AI_ANALYSIS_ENABLED=true\nOPENAI_API_KEY=fake-key\nOPENAI_MODEL=\n", encoding="utf-8")
    settings = AISettings(_env_file=config)
    assert settings.unavailable_reason() is None and settings.selected_model == "gpt-6-luna"
    monkeypatch.setenv("OPENAI_MODEL", "project-model")
    monkeypatch.setenv("AI_ANALYSIS_ENABLED", "false")
    settings = AISettings(_env_file=config)
    assert settings.selected_model == "project-model" and settings.unavailable_reason() == "DISABLED"


def test_analysis_persists_grounded_output_and_reuses_unchanged_attempt(client, ai_dependencies, csv_file, submit):
    finding = create_finding(client, csv_file, submit)
    provider = ProviderStub()
    ai_dependencies(provider=provider)
    endpoint = f"{PATH}/insights/{finding['id']}/analyses"
    assert client.get(endpoint).json()["total"] == 0
    assert client.post(endpoint, json={"attributed_purchases": 999}).status_code == 422
    response = client.post(endpoint)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "COMPLETED" and record["is_current"]
    assert record["model"] == "mock-model" and len(record["evidence_fingerprint"]) == 64
    assert record["provider_usage"]["total_tokens"] == 470
    cited = record["evidence_references"][0]
    assert cited["path"] == "current.metrics.cpa" and Decimal(cited["value"]) == 20
    assert provider.calls[0]["evidence"]["campaign"]["campaign_name"] == finding["campaign_snapshot"]["campaign_name"]
    assert "source_import_id" not in json.dumps(provider.calls[0])
    reused = client.post(endpoint)
    assert reused.status_code == 200 and reused.json()["id"] == record["id"]
    assert len(provider.calls) == 1
    assert client.get(f"{PATH}/ai/analyses/{record['id']}").json() == record
    assert submit(client, csv_file()).status_code == 201
    history = client.get(endpoint).json()
    assert history["total"] == 1 and not history["items"][0]["is_current"]
    assert history["items"][0]["structured_output"] == record["structured_output"]
    assert client.post(endpoint).status_code == 409


@pytest.mark.parametrize("changes", [
    {"evidence_references": ["current.metrics.profit"]},
    {"evidence_references": ["current.metrics.cpa", "current.metrics.cpa"]},
    {"evidence_references": ["rule.policy_id"]},
    {"evidence_references": ["current.start"]},
    {"evidence_references": ["current.metrics.cpa", "baseline.metrics.cpa"]},
    {"possible_explanations": ["Traffic might have changed."]},
    {"action_rationale": None},
    {"executive_summary": "The campaign gained 99 purchases."},
    {"finding_id": 999},
    {"recommended_action_type": "EXECUTE_BUDGET_CHANGE"},
])
def test_invalid_provider_output_is_recoverable_and_audited(client, ai_dependencies, csv_file, submit, changes):
    finding = create_finding(client, csv_file, submit)
    provider = ProviderStub(output=sample_output(finding["id"], **changes))
    ai_dependencies(provider=provider)
    endpoint = f"{PATH}/insights/{finding['id']}/analyses"
    response = client.post(endpoint)
    assert response.status_code == 502 and response.json()["error"]["code"] == "AI_INVALID_OUTPUT"
    entry = client.get(endpoint).json()["items"][0]
    assert entry["status"] == "FAILED" and entry["structured_output"] is None
    provider.output = None
    assert client.post(endpoint).status_code == 201
    assert client.get(endpoint).json()["total"] == 2


def test_provider_timeout_is_audited_and_rate_limit_blocks_retries(client, ai_dependencies, csv_file, submit):
    finding = create_finding(client, csv_file, submit)
    provider = ProviderStub(failure=ProviderFailure("AI_PROVIDER_TIMEOUT", "Timed out. You can retry.", 504))
    ai_dependencies(ENABLED.model_copy(update={"ai_request_limit_per_hour": 1}), provider)
    endpoint = f"{PATH}/insights/{finding['id']}/analyses"
    assert client.post(endpoint).status_code == 504
    assert client.get(endpoint).json()["items"][0]["error_code"] == "AI_PROVIDER_TIMEOUT"
    response = client.post(endpoint)
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert len(provider.calls) == 1


def test_data_quality_output_requires_measurement_first():
    snapshot = {"finding_id": 1, "evidence": {
        "rule": {"category": "DATA_QUALITY"}, "evidence_quality": "BLOCKED",
        "current": {"observed_days": 5, "missing_dates": ["2026-11-10"]},
    }}
    good = sample_output(1, evidence_references=["current.observed_days"])
    assert validate_output(good, snapshot).recommended_action_type == "INVESTIGATE"
    with pytest.raises(ValueError, match="QUALITY_ACTION"):
        validate_output({**good, "recommended_action_type": "CONSIDER_REALLOCATION"}, snapshot)


def mock_provider_transport(monkeypatch, handler):
    from openai import OpenAI

    def factory(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("app.ai_provider.OpenAI", factory)
    monkeypatch.setattr("app.ai_provider.time.sleep", lambda _: None)


def sdk_response(output):
    return httpx.Response(200, json={
        "object": "response", "id": "resp_test", "created_at": 0, "status": "completed",
        "model": "mock-model", "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}]}],
        "usage": {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    })


def test_official_sdk_parses_the_structured_response_with_mock_transport(monkeypatch):
    def reply(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/responses" and body["store"] is False
        assert body["model"] == "mock-model" and body["text"]["format"]["strict"]
        assert body["max_output_tokens"] <= 2800 and "tools" not in body
        assert body["text"]["format"]["schema"]["properties"]["evidence_references"]["items"]["enum"] == ["current.metrics.cpa"]
        return sdk_response(sample_output(1))
    mock_provider_transport(monkeypatch, reply)
    snapshot = {"finding_id": 1, "evidence": {"current": {"metrics": {"cpa": "20"}}}}
    result = OpenAIProvider().generate(ENABLED, snapshot)
    assert isinstance(result.output, AnalysisOutput)
    assert result.output.finding_id == 1 and result.usage["total_tokens"] == 300


def test_sdk_response_passes_evidence_contract_and_persists_with_typed_provider_output(client, ai_dependencies, csv_file, submit, monkeypatch):
    finding = create_finding(client, csv_file, submit)

    def reply(request):
        body = json.loads(request.content)
        payload = json.loads(body["input"][0]["content"])
        assert payload["evidence"]["campaign"]["campaign_name"] == "Fixture Search"
        assert set(payload["required_evidence_references"]) == {
            f"{period}.metrics.{metric}" for period in ("current", "baseline") for metric in ("cpa", "cpc", "purchase_cvr")
        }
        assert set(payload["evidence"]["cpa_drivers"]) == {"cpc_change_pct", "purchase_cvr_change_pct"}
        return sdk_response(sample_output(finding["id"]))

    mock_provider_transport(monkeypatch, reply)
    ai_dependencies(provider=OpenAIProvider())
    endpoint = f"{PATH}/insights/{finding['id']}/analyses"
    response = client.post(endpoint)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "COMPLETED" and record["provider_usage"]["total_tokens"] == 300
    assert client.get(endpoint).json()["items"][0]["id"] == record["id"]


def test_sdk_provider_timeout_retries_only_once(monkeypatch):
    count = 0
    def timeout(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("mock timeout", request=request)

    mock_provider_transport(monkeypatch, timeout)
    with pytest.raises(ProviderFailure) as error:
        OpenAIProvider().generate(ENABLED, {"finding_id": 1, "evidence": {}})
    assert error.value.code == "AI_PROVIDER_TIMEOUT"
    assert count == 2


@pytest.mark.parametrize(("status", "code", "expected"), [
    (401, "invalid_api_key", "AI_PROVIDER_AUTH"),
    (404, "model_not_found", "AI_PROVIDER_MODEL_UNAVAILABLE"),
    (429, "insufficient_quota", "AI_PROVIDER_QUOTA"),
])
def test_provider_check_is_explicit_and_gate_failures_are_sanitized(client, ai_dependencies, monkeypatch, status, code, expected):
    methods = []

    def reply(request):
        methods.append(request.method)
        return httpx.Response(status, json={"error": {"message": "sensitive provider detail", "code": code}})

    mock_provider_transport(monkeypatch, reply)
    provider = OpenAIProvider()
    ai_dependencies(provider=provider)
    assert client.get(f"{PATH}/ai/status").json()["provider_status"] == "UNCHECKED"
    assert methods == []
    result = client.post(f"{PATH}/ai/status/check").json()
    assert result["reason"] == "PROVIDER_ERROR" and result["provider_error_code"] == expected
    assert "sensitive provider detail" not in str(result)
    assert client.get(f"{PATH}/ai/status").json() == result
    assert methods == ["GET"]
    with pytest.raises(ProviderFailure) as error:
        provider.generate(ENABLED, {"finding_id": 1, "evidence": {"current": {"observed_days": 7}}})
    assert error.value.code == expected
    assert methods == ["GET", "POST"]


@pytest.mark.postgres
def test_regeneration_preserves_history_and_deduplicates_idempotent_or_competing_requests(postgres, client_for, ai_dependencies, csv_file, submit):
    engine, _ = postgres
    provider = ProviderStub()
    ai_dependencies(provider=provider)
    with client_for(engine) as client:
        finding = create_finding(client, csv_file, submit)
        endpoint = f"{PATH}/insights/{finding['id']}/analyses"
        original = client.post(endpoint).json()
        body = {"regenerate_from": original["id"], "request_id": str(uuid4())}
        first = client.post(endpoint, json=body)
        assert first.status_code == 201, first.text
        replacement = first.json()
        assert replacement["id"] != original["id"]
        assert client.post(endpoint, json=body).json()["id"] == replacement["id"]
        assert client.post(endpoint, json={**body, "request_id": str(uuid4())}).json()["id"] == replacement["id"]
        assert client.post(endpoint).json()["id"] == replacement["id"]
        assert client.post(endpoint, json={"regenerate_from": 888, "request_id": str(uuid4())}).status_code == 409
        history = client.get(endpoint).json()["items"]
        assert [(row["id"], row["is_current"]) for row in history] == [(replacement["id"], True), (original["id"], False)]
        assert history[1]["structured_output"] == original["structured_output"]
        assert len(provider.calls) == 2


def test_offline_ai_contract_cases():
    results = evaluate_cases()
    assert sum(row["result"] == "FIXTURE_CONTRACT_PASSED" for row in results) == 6
    assert results[-1]["result"] == "SUPPRESSION_HAS_NO_ANALYSIS_TARGET"


@pytest.mark.postgres
def test_concurrent_provider_call_commits_snapshot_first_and_marks_inflight_stale(postgres, client_for, ai_dependencies, csv_file, submit):
    engine, _ = postgres
    started, release = Event(), Event()

    class PausedProvider(ProviderStub):
        def generate(self, settings, snapshot):
            assert engine.pool.checkedout() == 0
            with Session(engine) as db:
                pending = db.scalar(select(AIAnalysis))
                assert pending.status == "PENDING"
                assert pending.evidence_fingerprint == fingerprint(snapshot)
            started.set()
            assert release.wait(timeout=8)
            return super().generate(settings, snapshot)

    provider = PausedProvider()
    ai_dependencies(provider=provider)
    with client_for(engine) as client:
        finding = create_finding(client, csv_file, submit)
        endpoint = f"{PATH}/insights/{finding['id']}/analyses"
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.post, endpoint)
            try:
                assert started.wait(timeout=8)
                duplicate = client.post(endpoint)
                assert duplicate.status_code == 202 and duplicate.json()["status"] == "PENDING"
                assert submit(client, csv_file()).status_code == 201
            finally:
                release.set()
            response = pending.result(timeout=8)
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "STALE" and not response.json()["is_current"]
        history = client.get(endpoint).json()
        assert history["total"] == 1 and history["items"][0]["structured_output"]
        assert len(provider.calls) == 1
