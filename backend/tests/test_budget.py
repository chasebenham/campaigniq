from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.budget import benchmarks
from app.budget.modeling import exact_split, extrapolation, piecewise
from app.budget.schemas import DEFAULT_ASSUMPTIONS
from app.budget_models import BudgetScenarioCampaign, BudgetScenarioResult
from app.models import Campaign, DailyCampaignPerformance

D = Decimal
URL = "/api/v1/budget-lab"
START = date(2026, 9, 1)
END = date(2026, 9, 14)
TODAY = date(2026, 10, 15)
REFERENCE = {"start": str(START), "end": str(END)}
PLANNING = {"start": "2026-10-16", "end": "2026-11-12"}


@pytest.fixture(autouse=True)
def use_fixture_clock(monkeypatch):
    monkeypatch.setattr(benchmarks, "utc_today", lambda: TODAY)
    monkeypatch.setattr("app.budget.api.utc_today", lambda: TODAY)
    monkeypatch.setenv("DETECTION_MATURATION_DAYS", "7")
    monkeypatch.setenv("BUDGET_MIN_OBSERVED_DAYS", "14")


def test_decimal_rounding_and_marginal_spend_boundaries():
    assert exact_split(101, {17: D(1), 3: D(1), 8: D(1)}) == {3: 34, 8: 34, 17: 33}
    assert exact_split(99, {2: D("0.1"), 1: D("0.2")}) == {1: 66, 2: 33}
    for spend, expected in [(0, 0), (50, 5), (100, 10), (123, 12)]:
        result = piecewise(D(spend), D(100), D(10), D(20), DEFAULT_ASSUMPTIONS.base)
        assert result.purchases == D(expected)
        assert result.value == D(2 * expected * 10)
        if spend:
            assert result.cpa == D(spend) / expected
            assert abs(result.roas - D(20 * expected) / spend) < D("1e-26")
        else:
            assert result.cpa is None and result.roas is None
    for amount, band in [("100", "none"), ("100.01", "modest"), ("110", "modest"),
                         ("110.01", "elevated"), ("150", "elevated"), ("150.01", "substantial")]:
        assert extrapolation(D(amount), D(100)) == band


def portfolio(client, csv_file, submit, engine):
    records = []
    for day_index in range(28):
        day = str(START + timedelta(days=day_index))
        for key, name, platform, spend, purchases, value, method in [
            ("trail", "Trail Search", "GOOGLE_ADS", "10", "1", "20", "LAST_CLICK"),
            ("gear", "All-Weather Gear", "META_ADS", "20", "1", "40", "LAST_CLICK"),
            ("linear", "Linear Credit", "META_ADS", "20", "1", "40", "LINEAR"),
            ("gap", "Reporting Gap", "GOOGLE_ADS", "10", "1", "20", "LAST_CLICK"),
            ("no-credit", "Zero Credit", "GOOGLE_ADS", "5", "0", "0", "LAST_CLICK"),
            ("unknown", "Unknown Context", "GOOGLE_ADS", "5", "1", "10", "LAST_CLICK"),
        ]:
            if key == "gap" and day_index == 3:
                continue
            records.append(dict(date=day, campaign_id=key, campaign_name=name, platform=platform,
                                spend=spend, attributed_purchases=purchases, attributed_purchase_value=value,
                                attribution_method=method))
    assert submit(client, csv_file(*records)).status_code == 201
    # Canonical CSV validation blocks unknown definitions. Cover a legacy database record separately.
    with engine.begin() as db:
        db.execute(update(DailyCampaignPerformance).where(
            DailyCampaignPerformance.campaign_id == select(Campaign.id).where(
                Campaign.external_campaign_id == "unknown").scalar_subquery(),
        ).values(attribution_method="UNKNOWN"))
    result = client.get(f"{URL}/eligible-campaigns", params={"start_date": START, "end_date": END})
    assert result.status_code == 200, result.text
    return {row["campaign_name"]: row for row in result.json()["items"]}


def plan(rows, names=("Trail Search", "All-Weather Gear"), amounts=("280", "583"), mode="DOLLARS", budget="863"):
    ids = [rows[name]["campaign_id"] for name in names]
    return {
        "name": "Fictional fall reallocation", "reference": REFERENCE, "planning": PLANNING,
        "total_budget": budget, "mode": mode, "campaign_ids": ids,
        "allocations": [{"campaign_id": key, "value": value} for key, value in zip(ids, amounts, strict=True)],
        "assumptions": {
            "conservative": {"cpa_change_pct": "15", "marginal_cpa_change_pct": "30", "value_per_purchase_change_pct": "-5"},
            "base": {"cpa_change_pct": "0", "marginal_cpa_change_pct": "15", "value_per_purchase_change_pct": "0"},
            "optimistic": {"cpa_change_pct": "-5", "marginal_cpa_change_pct": "5", "value_per_purchase_change_pct": "3"},
        },
    }


def calculate(client, data):
    response = client.post(f"{URL}/calculate", json=data)
    assert response.status_code == 200, response.text
    return response.json()


def test_benchmarks_default_reference_gaps_context_filters_and_maturation(client, csv_file, submit, memory_engine):
    rows = portfolio(client, csv_file, submit, memory_engine)
    assert client.get(f"{URL}/assumptions").json()["reference"] == {"start": "2026-09-01", "end": "2026-09-28"}
    assert rows["Trail Search"]["eligible"] is True
    assert D(rows["Trail Search"]["average_daily_spend"]) == 10
    assert rows["Reporting Gap"]["eligible"] is False
    assert rows["Reporting Gap"]["period"]["missing_dates"] == ["2026-09-04"]
    assert rows["Unknown Context"]["eligible"] is False
    assert rows["Unknown Context"]["period"]["metrics"]["attributed_purchases"] is None
    assert rows["Zero Credit"]["eligible"] is False
    assert D(rows["Zero Credit"]["period"]["metrics"]["attributed_purchases"]) == 0
    listed = client.get(f"{URL}/eligible-campaigns", params={
        "platform": "META_ADS", "page_size": 1, "page": 2,
    }).json()
    assert listed["total"] == 2 and listed["items"][0]["campaign_name"] == "Linear Credit"
    assert client.get(f"{URL}/eligible-campaigns", params={"q": "weather"}).json()["total"] == 1
    assert client.get(f"{URL}/eligible-campaigns", params={"campaign_id": rows["Trail Search"]["campaign_id"]}).json()["total"] == 1
    short = client.get(f"{URL}/eligible-campaigns", params={
        "start_date": START, "end_date": "2026-09-13", "campaign_id": rows["Trail Search"]["campaign_id"],
    }).json()["items"][0]
    assert short["period"]["complete"] and not short["eligible"]
    immature = client.get(f"{URL}/eligible-campaigns", params={"start_date": "2026-09-28", "end_date": "2026-10-08"})
    assert immature.status_code == 422 and immature.json()["error"]["code"] == "IMMATURE_REFERENCE"


def test_plan_uses_normalized_history_and_weighted_scenario_outputs(client, csv_file, submit, memory_engine):
    rows = portfolio(client, csv_file, submit, memory_engine)
    result = calculate(client, plan(rows))
    assert result["reference_days"] == 14 and result["planning_days"] == 28
    assert D(result["observed"]["spend"]) == 420
    assert D(result["normalized"]["spend"]) == 840
    assert D(result["normalized"]["purchases"]) == 56
    assert D(result["normalized"]["value"]) == 1680
    assert D(result["normalized"]["cpa"]) == 15
    assert D(result["normalized"]["roas"]) == 2
    base = result["scenarios"]["base"]["portfolio"]
    assert D(base["spend"]) == 863 and D(base["purchases"]) == 57 and D(base["value"]) == 1720
    assert abs(D(base["cpa"]) - D(863) / 57) < D("1e-26")
    assert abs(D(base["roas"]) - D(1720) / 863) < D("1e-26")
    with localcontext() as context:
        context.prec = 40
        expected = {
            "conservative": (D(56) / D("1.15") + D(23) / D("29.90"),
                             D(1596) / D("1.15") + D(23) / D("29.90") * 38),
            "optimistic": (D(56) / D(".95") + D(23) / D("19.95"),
                           D("1730.4") / D(".95") + D(23) / D("19.95") * D("41.2")),
        }
        for name, (credit, value) in expected.items():
            assert abs(D(result["scenarios"][name]["portfolio"]["purchases"]) - credit) < D("1e-35")
            assert abs(D(result["scenarios"][name]["portfolio"]["value"]) - value) < D("1e-35")
    assert any(row["code"] == "EXTRAPOLATION_MODEST" for row in result["warnings"])
    assert any(row["code"] == "CROSS_PLATFORM_ATTRIBUTION" for row in result["warnings"])
    high = calculate(client, plan(rows, amounts=("0", "1001"), budget="1001"))
    assert {"EXTRAPOLATION_SUBSTANTIAL", "PORTFOLIO_INCREMENTAL_EXPOSURE", "ABOVE_DAILY_PEAK"} <= {
        row["code"] for row in high["warnings"]
    }


def test_allocation_presets_validation_zero_and_mixed_reporting_contexts(client, csv_file, submit, memory_engine):
    rows = portfolio(client, csv_file, submit, memory_engine)
    base = plan(rows)
    selection = {key: base[key] for key in ("reference", "planning", "campaign_ids", "total_budget")}
    for method, expected in [("equal", [D("0.50"), D("0.51")]), ("historical", [D("0.34"), D("0.67")])]:
        response = client.post(f"{URL}/allocations", json={**selection, "total_budget": "1.01", "method": method})
        assert response.status_code == 200, response.text
        assert sorted(D(row["dollars"]) for row in response.json()) == expected
        assert sum(D(row["percent"]) for row in response.json()) == 100
    for patch in [{"total_budget": "NaN"}, {"total_budget": "-1"}, {"total_budget": "863.01"},
                  {"mode": "PERCENT"}, {"planning": {"start": "2026-09-15", "end": "2026-10-04"}},
                  {"campaign_ids": [base["campaign_ids"][0]]}]:
        assert client.post(f"{URL}/calculate", json={**base, **patch}).status_code == 422
    valid_pct = calculate(client, plan(rows, amounts=("33.33", "66.67"), mode="PERCENT", budget="1.01"))
    assert D(valid_pct["scenarios"]["base"]["portfolio"]["spend"]) == D("1.01")
    zero = calculate(client, plan(rows, amounts=("0", "0"), budget="0"))["scenarios"]["base"]["portfolio"]
    assert D(zero["purchases"]) == 0 and zero["cpa"] is None and zero["roas"] is None
    mixed = calculate(client, plan(rows, names=("Trail Search", "Linear Credit")))
    assert mixed["scenarios"]["base"]["portfolio"]["purchases"] is None
    assert all(item["modeled"]["purchases"] is not None for item in mixed["scenarios"]["base"]["campaigns"])
    assert any(row["code"] == "ATTRIBUTION_CONTEXTS_DIFFER" for row in mixed["warnings"])
    blocked = plan(rows, names=("Trail Search", "All-Weather Gear", "Reporting Gap"), amounts=("280", "582", "1"))
    assert client.post(f"{URL}/calculate", json=blocked).json()["error"]["code"] == "INELIGIBLE_ALLOCATION"


def test_postgres_scenario_snapshot_clone_stale_and_migration(postgres, client_for, csv_file, submit):
    engine, _ = postgres
    with client_for(engine) as client:
        rows = portfolio(client, csv_file, submit, engine)
        data = plan(rows, names=("Trail Search", "All-Weather Gear", "Reporting Gap"), amounts=("280", "583", "0"))
        calculation = calculate(client, data)
        hash_value = calculation["evidence_fingerprint"]
        response = client.post(f"{URL}/scenarios", json={"plan": data, "evidence_fingerprint": hash_value})
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["status"] == "CURRENT" and saved["result"] == calculation
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261124_0008"
        assert db.scalar(select(func.count(BudgetScenarioResult.scenario_id))) == 1
        assert db.scalar(select(func.count(BudgetScenarioCampaign.campaign_id))) == 3
    # Reopen from a new connection and backfill a persisted gap for just one selected campaign.
    engine.dispose()
    with client_for(engine) as client:
        key = saved["id"]
        assert client.get(f"{URL}/scenarios/{key}").json() == saved
        assert submit(client, csv_file(dict(
            date="2026-09-29", campaign_id="trail", campaign_name="Trail Search", spend="10",
            attributed_purchases="1", attributed_purchase_value="20",
        ))).status_code == 201
        assert client.get(f"{URL}/scenarios/{key}").json() == saved
        assert submit(client, csv_file(dict(date="2026-09-04", campaign_id="gap", campaign_name="Reporting Gap",
                                           spend="10", attributed_purchases="1", attributed_purchase_value="20"))).status_code == 201
        stale = client.get(f"{URL}/scenarios/{key}").json()
        assert stale["status"] == "STALE" and stale["result"] == calculation
        conflict = client.post(f"{URL}/scenarios", json={"plan": data, "evidence_fingerprint": hash_value})
        assert conflict.status_code == 409
        copied = client.post(f"{URL}/scenarios/{key}/clone", json={}).json()
        assert copied["id"] != key and copied["cloned_from_id"] == key
        assert copied["calculated_at"] == saved["calculated_at"]
        assert copied["result"] == calculation and copied["status"] == "STALE"
        assert client.get(f"{URL}/scenarios", params={"page_size": 1}).json()["total"] == 2
    with Session(engine) as db:
        assert db.scalar(select(func.count(Campaign.id))) == 6
        assert db.scalar(select(func.count(DailyCampaignPerformance.id))) == 169
