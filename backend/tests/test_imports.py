from decimal import Decimal

import pytest

from app.validation import InvalidCSV, parse_csv

IMPORTS = "/api/v1/imports"


def test_valid_csv_accepts_zero_and_fractional_credit(csv_file):
    integer, fractional = parse_csv(csv_file(
        {"attributed_purchases": "0", "attributed_purchase_value": "0"},
        {"attributed_purchases": "1.125", "attribution_method": "DATA_DRIVEN"},
    ))
    assert not integer.issues and not fractional.issues
    assert integer.metrics["attributed_purchases"] == 0
    assert fractional.metrics["attributed_purchases"] == Decimal("1.125")
    assert fractional.metrics["spend"] == Decimal("125.25")


@pytest.mark.parametrize(("change", "code"), [
    ({"spend": "NaN"}, "INVALID_NUMBER"),
    ({"spend": "20.00001"}, "NUMERIC_PRECISION"),
    ({"clicks": "-1"}, "NEGATIVE_NUMBER"),
    ({"clicks": "1250"}, "CLICKS_EXCEED_IMPRESSIONS"),
    ({"attributed_purchase_value": "-20"}, "NEGATIVE_NUMBER"),
    ({"date": "2026-02-29"}, "INVALID_DATE"),
    ({"campaign_id": ""}, "REQUIRED"),
    ({"currency": "EUR"}, "UNSUPPORTED_CURRENCY"),
    ({"platform": "BING"}, "UNSUPPORTED_PLATFORM"),
    ({"conversion_action": "LEAD"}, "UNRECOGNIZED_DEFINITION"),
    ({"date_basis": "UNKNOWN"}, "INCOMPATIBLE_CONTEXT"),
    ({"attribution_window": "7D_CLICK_1D_VIEW"}, "INCOMPATIBLE_CONTEXT"),
    ({"attributed_purchases": "0.9"}, "FRACTIONAL_LAST_CLICK"),
])
def test_validation_errors(csv_file, change, code):
    [row] = parse_csv(csv_file(change))
    assert code in {issue.error_code for issue in row.issues}
    assert row.number == 2


def test_missing_header(csv_file):
    with pytest.raises(InvalidCSV, match="Missing columns: currency"):
        parse_csv(csv_file().replace(b",currency", b",country"))


def test_import_partial_success_history_and_safe_duplicates(client, csv_file, submit):
    contents = csv_file({}, {}, {"campaign_id": "rejected", "currency": "EUR"})
    preview = submit(client, contents, confirm=False).json()
    assert (preview["valid_rows"], preview["duplicate_rows"], preview["rejected_rows"]) == (1, 1, 1)
    assert not client.get(IMPORTS).json()["items"]
    commit = submit(client, contents, token=preview["token"])
    assert commit.status_code == 201, commit.text
    record = commit.json()
    assert record["import_status"] == "COMPLETED_WITH_ERRORS"
    issue = client.get(f"{IMPORTS}/{record['id']}").json()["issues"]["items"][0]
    assert (issue["row_number"], issue["field_name"]) == (4, "currency")
    stale = submit(client, contents, token=preview["token"])
    assert stale.status_code == 409
    duplicate = submit(client, csv_file()).json()
    assert (duplicate["valid_rows"], duplicate["duplicate_rows"], duplicate["import_status"]) == (0, 1, "NO_NEW_ROWS")


def test_conflicting_rows_preserve_persisted_metrics(client, csv_file, submit):
    conflict = submit(client, csv_file({}, {"spend": "150"})).json()
    details = client.get(f"{IMPORTS}/{conflict['id']}").json()
    assert conflict["rejected_rows"] == 2
    assert {issue["error_code"] for issue in details["issues"]["items"]} == {"FILE_CONFLICT"}
    assert submit(client, csv_file()).status_code == 201
    changed = submit(client, csv_file({"spend": "200"}), confirm=False).json()
    assert changed["issues"][0]["error_code"] == "EXISTING_CONFLICT"
    assert Decimal(client.get("/api/v1/analytics/overview").json()["metrics"]["spend"]) == Decimal("125.25")


def test_attribution_methods_cannot_change_inside_a_campaign(client, csv_file, submit):
    response = submit(client, csv_file({}, {
        "date": "2026-08-26", "attribution_method": "DATA_DRIVEN", "attributed_purchases": "0.5",
    }), confirm=False).json()
    assert response["rejected_rows"] == 2
    assert response["error_counts"] == {"CAMPAIGN_CONTEXT_CONFLICT": 2}
    assert submit(client, csv_file()).status_code == 201
    changed = submit(client, csv_file({
        "date": "2026-08-26", "attribution_method": "LINEAR", "attributed_purchases": "0.5",
    }), confirm=False).json()
    assert changed["error_counts"] == {"CAMPAIGN_CONTEXT_CONFLICT": 1}
