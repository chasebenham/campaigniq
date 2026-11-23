from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Iterable

from pydantic import BaseModel, field_serializer

MAX_SAFE_JSON_INTEGER = 2**53 - 1


@dataclass(frozen=True)
class Totals:
    impressions: int = 0
    clicks: int = 0
    spend: Decimal = Decimal(0)
    attributed_purchases: Decimal = Decimal(0)
    attributed_purchase_value: Decimal = Decimal(0)


class Metrics(BaseModel):
    impressions: int
    clicks: int
    spend: Decimal
    attributed_purchases: Decimal | None
    attributed_purchase_value: Decimal | None
    ctr: Decimal | None
    cpc: Decimal | None
    cpm: Decimal | None
    purchase_cvr: Decimal | None
    cpa: Decimal | None
    roas: Decimal | None
    attributed_aov: Decimal | None

    @field_serializer("impressions", "clicks", when_used="json")
    def serialize_count(self, value: int) -> int | str:
        return value if value <= MAX_SAFE_JSON_INTEGER else str(value)


def sum_totals(rows: Iterable[Totals]) -> Totals:
    impressions = clicks = 0
    spend = purchases = value = Decimal(0)
    with localcontext() as context:
        context.prec = 40
        for row in rows:
            impressions += row.impressions
            clicks += row.clicks
            spend += row.spend
            purchases += row.attributed_purchases
            value += row.attributed_purchase_value
    return Totals(impressions, clicks, spend, purchases, value)


def ratio(numerator: Decimal | int, denominator: Decimal | int, multiplier: int = 1):
    if not denominator:
        return None
    with localcontext() as context:
        context.prec = 40
        return Decimal(numerator) * multiplier / Decimal(denominator)


def calculate(totals: Totals, *, conversions_available: bool = True) -> Metrics:
    impressions, clicks, spend = totals.impressions, totals.clicks, totals.spend
    purchases, value = totals.attributed_purchases, totals.attributed_purchase_value

    return Metrics(
        impressions=impressions,
        clicks=clicks,
        spend=spend,
        attributed_purchases=purchases if conversions_available else None,
        attributed_purchase_value=value if conversions_available else None,
        ctr=ratio(clicks, impressions, 100),
        cpc=ratio(spend, clicks),
        cpm=ratio(spend, impressions, 1000),
        purchase_cvr=ratio(purchases, clicks, 100) if conversions_available else None,
        cpa=ratio(spend, purchases) if conversions_available else None,
        roas=ratio(value, spend) if conversions_available else None,
        attributed_aov=ratio(value, purchases) if conversions_available else None,
    )
