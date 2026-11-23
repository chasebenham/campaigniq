import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Campaign, DailyCampaignPerformance, DataImport
from app.seed import seed

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres():
    url = os.getenv("CAMPAIGNIQ_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CAMPAIGNIQ_TEST_DATABASE_URL to run isolated PostgreSQL integration tests.")
    schema = f"ciq_test_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    config = Config(Path(__file__).resolve().parents[1] / "alembic.ini")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine, config
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_migrations_are_reversible_and_match_models(postgres):
    engine, config = postgres
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.check(config)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261123_0001"
        assert set(inspect(connection).get_table_names()) >= {
            "campaigns", "daily_campaign_performance", "data_imports", "import_validation_errors",
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
