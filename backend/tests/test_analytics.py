from decimal import Decimal


def test_filtering_sorting_scope_and_aggregation(client, csv_file, submit):
    response = submit(client, csv_file(
        {},
        {"date": "2026-08-26", "clicks": "20", "spend": "4.75", "attributed_purchases": "0", "attributed_purchase_value": "0"},
        {"platform": "META_ADS", "campaign_name": "Fixture Meta", "clicks": "80", "spend": "70", "attributed_purchases": "3", "attributed_purchase_value": "90"},
    ))
    assert response.status_code == 201, response.text
    overview = client.get("/api/v1/analytics/overview").json()
    assert overview["record_count"] == 3
    assert overview["platform_attributed_overlap"]
    assert Decimal(overview["metrics"]["cpa"]) == Decimal("25")
    assert Decimal(overview["metrics"]["roas"]) == Decimal("3.2")
    filtered = client.get("/api/v1/analytics/overview", params={
        "platform": "GOOGLE_ADS", "start_date": "2026-08-26", "end_date": "2026-08-26",
    }).json()
    assert filtered["record_count"] == 1
    assert filtered["first_date"] == filtered["last_date"] == "2026-08-26"
    assert Decimal(filtered["metrics"]["spend"]) == Decimal("4.75")
    assert filtered["metrics"]["cpa"] is None
    response = client.get("/api/v1/campaigns", params={"sort": "spend", "direction": "asc", "page_size": 1})
    campaigns = response.json()
    assert campaigns["total"] == 2
    [campaign] = campaigns["items"]
    assert campaign["platform"] == "META_ADS"
    assert campaign["external_campaign_id"] == "fixture-id"
    data = client.get(f"/api/v1/campaigns/{campaign['id']}/performance").json()
    assert data["trends"]["items"][0]["date"] == "2026-08-25"
    assert data["report"]["metrics"]["clicks"] == 80
    assert client.get("/api/v1/analytics/overview?start_date=2026-08-26&end_date=2026-08-25").status_code == 422
    assert client.get("/api/v1/campaigns?page_size=101").status_code == 422


def test_mixed_contexts_suppress_conversion_totals_and_entire_trend(client, csv_file, submit):
    assert submit(client, csv_file({}, {
        "date": "2026-08-26", "campaign_id": "meta-dda", "platform": "META_ADS",
        "attribution_method": "DATA_DRIVEN", "attributed_purchases": "2.5",
    })).status_code == 201
    report = client.get("/api/v1/analytics/overview").json()
    assert report["conversion_status"] == "incompatible"
    assert report["metrics"]["cpa"] is None
    assert Decimal(report["metrics"]["spend"]) == Decimal("250.50")
    trend = client.get("/api/v1/analytics/trends").json()["items"]
    assert len(trend) == 2 and all(day["metrics"]["roas"] is None for day in trend)
    platforms = client.get("/api/v1/analytics/platforms").json()
    assert [x["conversion_status"] for x in platforms] == ["available", "available"]
    assert Decimal(platforms[1]["metrics"]["attributed_purchases"]) == Decimal("2.5")
