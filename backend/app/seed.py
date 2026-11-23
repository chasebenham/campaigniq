"""Load the fictional Northstar Outfitters portfolio."""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from random import Random

from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from app.db import SessionLocal, lock_performance_writes
from app.domain import CANONICAL_CONTEXT, CampaignStatus, ImportStatus, Platform, SourceType
from app.models import Campaign, DailyCampaignPerformance, DataImport

FIRST_DATE = date(2026, 8, 25)
DAYS = 90
LAST_DATE = FIRST_DATE + timedelta(days=DAYS - 1)
SEED = 18273
FILENAME = "northstar-outfitters-fictional-v1"


@dataclass(frozen=True)
class Profile:
    code: str
    name: str
    platform: Platform
    pattern: str
    impressions: int
    ctr: float
    cpc: float
    cvr: float
    order_value: int
    target_cpa: int
    target_roas: str
    status: CampaignStatus = CampaignStatus.ACTIVE


G, M = Platform.GOOGLE_ADS, Platform.META_ADS
PORTFOLIO = (
    Profile("NS-G01", "Trail Collection Search", G, "stable", 9500, .055, 1.25, .052, 123, 26, "4.3"),
    Profile("NS-G02", "Everyday Essentials Shopping", G, "stable", 18000, .028, .91, .047, 96, 25, "3.8"),
    Profile("NS-G03", "New Customer Acquisition", G, "declining_efficiency", 9000, .047, 1.42, .043, 112, 35, "3.1"),
    Profile("NS-G04", "Hiking Essentials Promotion", G, "conversion_decline", 11500, .040, 1.22, .048, 115, 29, "3.8"),
    Profile("NS-G05", "All-Weather Gear Shopping", G, "scaling", 6900, .042, .89, .062, 135, 26, "4.0"),
    Profile("NS-G06", "Outdoor Apparel Broad Search", G, "inefficient_spend", 13500, .036, 1.35, .025, 107, 36, "3.0"),
    Profile("NS-G07", "Summit Layers Performance Max", G, "coverage_gap", 17800, .023, 1.18, .045, 118, 32, "3.5"),
    Profile("NS-G08", "Merino Accessories Search", G, "low_volume", 390, .034, .74, .021, 68, 32, "2.8", CampaignStatus.PAUSED),
    Profile("NS-M01", "Outdoor Lifestyle Prospecting", M, "stable", 34000, .014, 1.03, .030, 115, 39, "2.8"),
    Profile("NS-M02", "Fall Apparel Retargeting", M, "stable", 19000, .019, .84, .054, 102, 25, "3.8"),
    Profile("NS-M03", "Trail Running Lookalikes", M, "declining_efficiency", 31000, .013, .98, .032, 116, 36, "3.1"),
    Profile("NS-M04", "Cold Weather Essentials", M, "declining_efficiency", 27000, .014, .97, .033, 120, 35, "3.2"),
    Profile("NS-M05", "Weekend Adventure Creatives", M, "conversion_decline", 28000, .014, .93, .031, 108, 35, "3.0"),
    Profile("NS-M06", "Campfire Classics Retargeting", M, "scaling", 13000, .018, .79, .057, 115, 27, "3.8"),
    Profile("NS-M07", "Lifestyle Discovery Broad", M, "inefficient_spend", 29500, .012, 1.19, .021, 98, 43, "2.7"),
    Profile("NS-M08", "Alpine Collection Video", M, "coverage_gap", 24600, .012, .98, .029, 122, 38, "3.2"),
)

GAPS = {"NS-G07": range(44, 48), "NS-M08": range(70, 75)}
SPEND_SCALE = .57


def cents(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def generate_performance():
    rng = Random(SEED)
    for profile in PORTFOLIO:
        for day in range(DAYS):
            current_date = FIRST_DATE + timedelta(days=day)
            if day in GAPS.get(profile.code, ()):
                continue

            weekend = current_date.weekday() >= 5
            volume = (0.84 if profile.platform == G else 1.16) if weekend else 1
            cost = 0.94 if weekend else 1
            conversion = 0.93 if weekend else 1.04
            progress = max(0, day - 34) / 55

            if profile.pattern == "declining_efficiency":
                cost *= 1 + 0.55 * progress
                conversion *= 1 - 0.24 * progress
            elif profile.pattern == "conversion_decline" and day >= 55:
                conversion *= 0.57
            elif profile.pattern == "scaling":
                volume *= 1 + 0.38 * progress
                conversion *= 1 + 0.20 * progress
            elif profile.pattern == "inefficient_spend" and day >= 59:
                volume *= 1.32
                cost *= 1.35
                conversion *= 0.79

            impressions = round(profile.impressions * SPEND_SCALE * volume * rng.uniform(.84, 1.16))
            clicks = min(impressions, round(impressions * profile.ctr * rng.uniform(.88, 1.12)))
            spend = cents(clicks * profile.cpc * cost * rng.uniform(.89, 1.11))
            probability = profile.cvr * conversion * rng.uniform(.88, 1.12)
            purchases = sum(rng.random() < probability for _ in range(clicks))
            revenue = cents(sum(profile.order_value * rng.uniform(.75, 1.25) for _ in range(purchases)))
            yield profile, {
                "report_date": current_date,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "attributed_purchases": Decimal(purchases),
                "attributed_purchase_value": revenue,
                **asdict(CANONICAL_CONTEXT),
            }


def seed(session: Session) -> tuple[int, int]:
    lock_performance_writes(session)
    profiles = {(p.platform, p.code): p for p in PORTFOLIO}
    campaigns = {
        (c.platform, c.external_campaign_id): c
        for c in session.scalars(select(Campaign).where(
            tuple_(Campaign.platform, Campaign.external_campaign_id).in_(list(profiles))
        ))
    }
    created = 0
    for key, profile in profiles.items():
        if key in campaigns:
            continue
        campaign = Campaign(
            platform=profile.platform,
            external_campaign_id=profile.code,
            campaign_name=profile.name,
            objective="PURCHASES",
            status=profile.status,
            target_cpa=Decimal(profile.target_cpa),
            target_roas=Decimal(profile.target_roas),
            currency="USD",
            start_date=FIRST_DATE,
        )
        session.add(campaign)
        campaigns[key] = campaign
        created += 1
    session.flush()

    existing = {(campaign_id, report_date) for campaign_id, report_date in session.execute(select(
        DailyCampaignPerformance.campaign_id, DailyCampaignPerformance.report_date
    ).where(
        DailyCampaignPerformance.campaign_id.in_([campaign.id for campaign in campaigns.values()]),
        DailyCampaignPerformance.report_date.between(FIRST_DATE, LAST_DATE),
    ))}
    incompatible_campaigns = set(session.scalars(select(DailyCampaignPerformance.campaign_id).where(
        DailyCampaignPerformance.campaign_id.in_([campaign.id for campaign in campaigns.values()]),
        or_(*(getattr(DailyCampaignPerformance, field) != value
              for field, value in asdict(CANONICAL_CONTEXT).items())),
    ).distinct()))
    rows = []
    for profile, values in generate_performance():
        campaign = campaigns[(profile.platform, profile.code)]
        report_date = values["report_date"]
        if (
            (campaign.id, report_date) not in existing
            and campaign.id not in incompatible_campaigns
            and campaign.start_date <= report_date
            and (campaign.end_date is None or report_date <= campaign.end_date)
        ):
            rows.append(DailyCampaignPerformance(campaign_id=campaign.id, **values))

    if rows:
        data_import = DataImport(
            filename=FILENAME,
            total_rows=len(rows),
            valid_rows=len(rows),
            rejected_rows=0,
            duplicate_rows=0,
            import_status=ImportStatus.COMPLETED,
            source_type=SourceType.SYNTHETIC_SEED,
            validation_summary={"fictional": True, "seed_version": 1, "error_counts": {}},
        )
        session.add(data_import)
        session.flush()
        for row in rows:
            row.source_import_id = data_import.id
        session.add_all(rows)
    return created, len(rows)


def main() -> None:
    with SessionLocal.begin() as session:
        campaigns, rows = seed(session)
    print(f"Fictional Northstar Outfitters seed: {campaigns} campaigns and {rows} rows added.")


if __name__ == "__main__":
    main()
