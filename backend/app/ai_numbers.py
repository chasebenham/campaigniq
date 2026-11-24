"""Validate explicitly referenced quantities without parsing prose for financial meaning."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

from app.ai_diagnostics import NUMBER, OutputRejection

MONEY_KEYS = {"spend", "attributed_purchase_value", "cpc", "cpm", "cpa", "attributed_aov", "target_cpa"}
COUNT_KEYS = {"impressions", "clicks", "observed_days", "expected_days", "calendar_days", "fictional_days"}


def numeric_evidence(catalog: dict) -> dict:
    evidence = {}
    for path, value in catalog.items():
        key = path.rsplit(".", 1)[-1]
        if isinstance(value, bool):
            continue
        if key in MONEY_KEYS:
            precision, unit = 2, "USD"
        elif key in {"roas", "target_roas"}:
            precision, unit = 2, "multiple"
        elif key in {"purchase_cvr", "ctr"} or key.endswith("_pct"):
            precision, unit = 2, "percent"
        elif key in COUNT_KEYS or ".flags." in path and key == "count":
            precision, unit = 0, "count"
        elif key == "attributed_purchases":
            precision, unit = 6, "count"
        else:
            continue
        try:
            exact = Decimal(str(value))
        except InvalidOperation:
            continue
        if exact.is_finite():
            with localcontext() as context:
                context.prec = 64
                display = exact.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
            evidence[path] = (exact, display, unit)
    return evidence


def display_value(display: Decimal, unit: str) -> str:
    text = format(display, "f")
    if unit == "USD":
        return f"${text}" if display >= 0 else f"-${text[1:]}"
    return text + {"multiple": "×", "percent": "%", "count": ""}[unit]


def verified_number(value: str, expected: tuple[Decimal, Decimal, str], path: str, reference: str) -> None:
    exact, display, unit = expected
    match = re.fullmatch(r"(?P<sign>[−+-]?)(?P<currency>\$?)(?P<value>[0-9][0-9,.]*)(?P<suffix>[%x×]?)", value.strip()) if len(value) <= 72 else None
    if not match:
        raise OutputRejection("NUMERIC", "NUMERIC_FORMAT", path, "A decimal value with an optional applicable unit.",
                              {"reference": reference, "length": len(value)})
    sign, currency, number, suffix = match.groups()
    if not NUMBER.fullmatch(number):
        raise OutputRejection("NUMERIC", "NUMERIC_FORMAT", path, "Use decimal notation and standard comma grouping.", {"reference": reference})
    actual = Decimal(sign.replace("−", "-") + number.replace(",", ""))
    if (currency and unit != "USD") or (suffix == "%" and unit != "percent") or (suffix in {"x", "×"} and unit != "multiple"):
        raise OutputRejection("NUMERIC", "NUMERIC_UNIT", path, f"A value in {unit}.", {"reference": reference, "unit": currency or suffix})
    if actual not in {exact, display}:
        raise OutputRejection("NUMERIC", "NUMERIC_MISMATCH", path,
                              "The persisted value or its precise UI-rounded equivalent.",
                              {"reference": reference, "value": str(actual), "allowed_display_value": display_value(display, unit)})
