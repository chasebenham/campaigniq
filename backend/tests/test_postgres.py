from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Campaign, DailyCampaignPerformance, DataImport
from app.seed import seed
from evaluation.detection import evaluate_seed

pytestmark = pytest.mark.postgres


def test_migrations_are_reversible_and_match_models(postgres):
    engine, config = postgres
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.check(config)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261124_0005"
        assert set(inspect(connection).get_table_names()) >= {
            "campaigns", "daily_campaign_performance", "data_imports", "import_validation_errors",
            "detection_runs", "detection_findings", "detection_suppressions", "ai_analyses",
        }
        command.downgrade(config, "base")
        assert "campaigns" not in inspect(connection).get_table_names()
        command.upgrade(config, "head")


def test_seed_idempotency_and_persisted_counts(postgres, client_for, csv_file, submit):
    engine, _ = postgres
    with client_for(engine) as client:
        assert submit(client, csv_file()).status_code == 201
    with Session(engine) as session, session.begin():
        assert seed(session) == (16, 1431)
    with Session(engine) as session, session.begin():
        assert seed(session) == (0, 0)
        assert session.scalar(select(func.count(Campaign.id))) == 17
        assert session.scalar(select(func.count(DailyCampaignPerformance.id))) == 1432
        assert session.scalar(select(func.count(DataImport.id))) == 2
    with client_for(engine) as client:
        report = client.get("/api/v1/analytics/overview").json()
        assert report["observed_days"] == 90
        assert report["fictional_record_count"] == 1431
        campaign_list = client.get("/api/v1/campaigns").json()["items"]
        gap_campaign = next(row for row in campaign_list if row["external_campaign_id"] == "NS-G07")
        assert gap_campaign["missing_days"] == 4


def test_csv_postgres_persistence_context_filters_and_uniqueness(postgres, client_for, csv_file, submit):
    engine, _ = postgres
    with client_for(engine) as client:
        assert submit(client, csv_file(
            {"spend": "30.0001", "attributed_purchases": "3", "attributed_purchase_value": "99.99"},
            {"date": "2026-08-26", "spend": "10.9999", "attributed_purchases": "1", "attributed_purchase_value": "23.01"},
            {"platform": "META_ADS", "attribution_method": "LINEAR", "attributed_purchases": "1.125"},
        )).status_code == 201
    with client_for(engine) as client:
        response = client.get("/api/v1/analytics/overview?platform=GOOGLE_ADS").json()
        assert response["record_count"] == 2
        assert response["metrics"]["spend"] == "41.0000"
        assert float(response["metrics"]["cpa"]) == 10.25
        assert float(response["metrics"]["roas"]) == 3
        assert client.get("/api/v1/analytics/overview").json()["conversion_status"] == "incompatible"
        assert client.get("/api/v1/campaigns").json()["total"] == 2
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        campaign = session.scalar(select(Campaign).where(Campaign.platform == "GOOGLE_ADS"))
        session.add(Campaign(platform="GOOGLE_ADS", external_campaign_id=campaign.external_campaign_id,
                             campaign_name="Duplicate", start_date=campaign.start_date))


def test_concurrent_commits_revalidate_under_the_postgres_write_lock(postgres, client_for, csv_file, submit):
    engine, _ = postgres
    contents = csv_file()
    with client_for(engine) as client:
        preview = submit(client, contents, confirm=False).json()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, client, contents, token=preview["token"]) for _ in range(2)]
            assert sorted(future.result().status_code for future in futures) == [201, 409]
        assert client.get("/api/v1/imports").json()["total"] == 1
        assert client.get("/api/v1/analytics/overview").json()["record_count"] == 1


def test_detection_persistence_pagination_and_stale_history(postgres, client_for, csv_file, submit):
    engine, _ = postgres
    with Session(engine) as db, db.begin():
        assert seed(db) == (16, 1431)
    with client_for(engine) as client:
        params = {"evaluation_date": "2026-11-23"}
        response = client.post("/api/v1/detection/runs", json=params)
        assert response.status_code == 201, response.text
        run = response.json()
        assert run["campaign_count"] == 16 and run["finding_count"] > 1 and run["suppression_count"] > 0
        assert run["windows"]["current"]["end"] == "2026-11-15"
        repeated = client.post("/api/v1/detection/runs", json=params)
        assert repeated.status_code == 200 and repeated.json()["reused"]
        assert repeated.json()["id"] == run["id"]
        page = client.get("/api/v1/insights?platform=GOOGLE_ADS&category=PERFORMANCE_RISK&page_size=1").json()
        assert page["total"] >= 2 and len(page["items"]) == 1
        finding = page["items"][0]
        next_page = client.get("/api/v1/insights?platform=GOOGLE_ADS&category=PERFORMANCE_RISK&page_size=1&page=2").json()
        assert next_page["items"][0]["id"] != finding["id"]
        assert finding["campaign_snapshot"]["platform"] == "GOOGLE_ADS"
        assert finding["severity"] == "HIGH"
        assert finding["current_evidence"]["fictional_days"] == 7
        campaign = client.get(f"/api/v1/campaigns/{finding['campaign_id']}/insights?policy_id={finding['policy_id']}").json()
        assert campaign["items"][0]["id"] == finding["id"]
        assert client.get("/api/v1/insights?start_date=2026-11-24").json()["total"] == 0
        assert client.get("/api/v1/insights?severity=INVALID").status_code == 422
        suppressions = client.get(f"/api/v1/detection/runs/{run['id']}/suppressions?policy_id=D-03").json()
        assert suppressions["total"] > 0
        assert submit(client, csv_file()).status_code == 201
        assert client.get("/api/v1/insights/summary").json()["run"]["state"] == "STALE"
        assert client.get(f"/api/v1/insights/{finding['id']}").json()["state"] == "STALE"
        refreshed = client.post("/api/v1/detection/runs", json=params).json()
        assert refreshed["id"] != run["id"] and refreshed["state"] == "CURRENT"
        old = client.get(f"/api/v1/insights/{finding['id']}").json()
        assert old["state"] == "HISTORICAL" and old["fingerprint"] == finding["fingerprint"]
        older = client.post("/api/v1/detection/runs", json={"evaluation_date": "2026-11-09"}).json()
        assert older["state"] == "HISTORICAL"
        assert client.get("/api/v1/detection/runs").json()["total"] == 3
        assert client.get("/api/v1/detection/runs?end_date=2026-11-12&status=COMPLETED").json()["items"][0]["id"] == older["id"]
        assert client.get("/api/v1/analytics/overview").json()["record_count"] == 1432


def test_seed_scenario_evaluation_reports_candidates_and_suppressions(postgres):
    engine, _ = postgres
    with Session(engine) as db, db.begin():
        seed(db)
        report = evaluate_seed(db)
    assert report["fictional"]
    assert report["reporting_cutoffs"][0] == "2026-09-07"
    assert report["reporting_cutoffs"][-1] == "2026-11-22"
    assert report["by_policy"]["D-06"]["true_positives"] == 2
    assert report["by_policy"]["D-04"]["recall"] is None
    assert any(row["scenario"] == "low_volume" and row["reason"] == "INSUFFICIENT_VOLUME"
               for row in report["cohort_suppressions"])
