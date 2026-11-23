from decimal import Decimal

from app.metrics import Totals, calculate, sum_totals

D = Decimal


def test_all_kpis():
    result = calculate(Totals(2000, 80, D("120"), D("12"), D("360")))
    assert (result.ctr, result.cpc, result.cpm) == (D("4"), D("1.5"), D("60"))
    assert (result.purchase_cvr, result.cpa, result.roas, result.attributed_aov) == (
        D("15"), D("10"), D("3"), D("30"),
    )


def test_zero_denominators_are_null_but_zero_credit_is_real():
    empty = calculate(Totals())
    for key in ("ctr", "cpc", "cpm", "purchase_cvr", "cpa", "roas", "attributed_aov"):
        assert getattr(empty, key) is None
    no_sales = calculate(Totals(120, 20, D("12")))
    assert no_sales.attributed_purchases == no_sales.purchase_cvr == no_sales.roas == 0
    assert no_sales.cpa is None and no_sales.attributed_aov is None


def test_weighted_totals_and_decimal_precision():
    totals = sum_totals([
        Totals(500, 10, D("10.1001"), D("0.500000"), D("20.0011")),
        Totals(9500, 90, D("89.8999"), D("3.500000"), D("229.9989")),
    ])
    assert totals.spend == D("100.0000")
    result = calculate(totals)
    assert (result.cpa, result.roas, result.purchase_cvr, result.attributed_aov) == (
        D("25"), D("2.5"), D("4"), D("62.5"),
    )
    exact = calculate(Totals(9, 3, D("0.1001"), D("0.000001"), D("0.0003")))
    assert exact.cpa == D("100100")
    assert exact.attributed_aov == D("300")
    assert str(exact.ctr).startswith("33.3333333333333333333333333333333")


def test_incompatible_conversions_are_suppressed_independently_of_traffic():
    result = calculate(Totals(2000, 100, D(25), D(10), D(90)), conversions_available=False)
    assert result.ctr == 5
    assert result.spend == 25
    for key in ("attributed_purchases", "attributed_purchase_value", "purchase_cvr", "cpa", "roas", "attributed_aov"):
        assert getattr(result, key) is None


def test_json_counts_preserve_integers_beyond_browser_precision():
    result = calculate(Totals(9007199254740993, 1)).model_dump(mode="json")
    assert result["impressions"] == "9007199254740993"
    assert result["clicks"] == 1
