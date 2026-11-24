import csv
import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.validation import CSV_COLUMNS


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


@pytest.fixture
def memory_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client_for():
    def factory(engine):
        def session():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        return TestClient(app)
    yield factory
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(memory_engine, client_for):
    with client_for(memory_engine) as client:
        yield client


@pytest.fixture
def csv_file():
    def make(*changes):
        row = {
            "date": "2026-08-25", "platform": "GOOGLE_ADS", "campaign_id": "fixture-id",
            "campaign_name": "Fixture Search", "impressions": "1000", "clicks": "100",
            "spend": "125.25", "attributed_purchases": "5", "attributed_purchase_value": "550",
            "conversion_action": "PURCHASE", "attribution_method": "LAST_CLICK",
            "attribution_window": "7D_CLICK", "date_basis": "INTERACTION_DATE", "currency": "USD",
        }
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for change in changes or ({},):
            writer.writerow({**row, **change})
        return stream.getvalue().encode()
    return make


@pytest.fixture
def submit():
    def upload(client, contents, *, confirm=True, token=None):
        file = {"file": ("fixture.csv", contents, "text/csv")}
        if token is None:
            preview = client.post("/api/v1/imports/preview", files=file)
            if not confirm or preview.status_code != 200:
                return preview
            token = preview.json()["token"]
        return client.post("/api/v1/imports/commit", files=file, data={"preview_token": token})
    return upload
