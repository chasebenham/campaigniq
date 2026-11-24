import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import lock_performance_writes
from app.detection_config import POLICY_VERSION, DetectionConfig
from app.detection_evidence import CampaignFacts, Observation, Windows, reporting_windows
from app.detection_models import DetectionFinding, DetectionRun, DetectionSuppression
from app.detection_policies import evaluate_campaign
from app.domain import CONTEXT_FIELDS, ReportingContext, SourceType
from app.metrics import Totals
from app.models import Campaign, DailyCampaignPerformance, DataImport

MAX_CAMPAIGNS = 2000
EARLIEST_EVALUATION_DATE = date(1, 5, 1)


class RunTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class CampaignInput:
    campaign: CampaignFacts
    observations: list[Observation]


def canonical_json(data) -> str:
    return json.dumps(data, default=str, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def fingerprint(data) -> str:
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def source_version(db: Session) -> int:
    # Phase 1's performance observations are append-only through imports and seeding.
    return db.scalar(select(func.max(DailyCampaignPerformance.id))) or 0


def active_run(db: Session) -> DetectionRun | None:
    return db.scalars(select(DetectionRun).where(DetectionRun.status == "COMPLETED")
                      .order_by(DetectionRun.evaluation_date.desc(), DetectionRun.id.desc()).limit(1)).first()


def gather_inputs(db: Session, windows: Windows, *, campaign_ids: list[int] | None = None,
                  seed_only: bool = False) -> list[CampaignInput]:
    campaign_query = select(Campaign).where(
        Campaign.start_date <= windows.current.end,
        (Campaign.end_date.is_(None) | (Campaign.end_date >= windows.current.start)),
    )
    if campaign_ids is not None:
        campaign_query = campaign_query.where(Campaign.id.in_(campaign_ids))
    campaigns = list(db.scalars(campaign_query.order_by(Campaign.id).limit(MAX_CAMPAIGNS + 1)))
    if len(campaigns) > MAX_CAMPAIGNS:
        raise RunTooLarge(f"A run supports up to {MAX_CAMPAIGNS:,} campaigns overlapping the current window.")

    p = DailyCampaignPerformance
    observations = defaultdict(list)
    if campaigns:
        statement = select(p, DataImport.source_type).join(DataImport).where(
            p.campaign_id.in_([campaign.id for campaign in campaigns]),
            p.report_date.between(windows.history.start, windows.current.end),
        ).order_by(p.campaign_id, p.report_date, p.id)
        if seed_only:
            statement = statement.where(DataImport.source_type == SourceType.SYNTHETIC_SEED)
        for row, provenance in db.execute(statement):
            observations[row.campaign_id].append(Observation(
                date=row.report_date,
                context=ReportingContext(*(getattr(row, field) for field in CONTEXT_FIELDS)),
                totals=Totals(*(getattr(row, field) for field in Totals.__dataclass_fields__)),
                fictional=provenance == SourceType.SYNTHETIC_SEED,
            ))
    return [
        CampaignInput(
            CampaignFacts(**{field: getattr(campaign, field) for field in CampaignFacts.__dataclass_fields__}),
            observations[campaign.id],
        )
        for campaign in campaigns
    ]


def execute_run(db: Session, as_of: date | None, configuration: DetectionConfig) -> tuple[DetectionRun, bool]:
    started_at = datetime.now(timezone.utc)
    lock_performance_writes(db)
    if as_of is None:
        last_date = db.scalar(select(func.max(DailyCampaignPerformance.report_date)))
        # Anchor old datasets to their last reporting day. Recent data still observes the maturity cutoff.
        if last_date and (started_at.date() - last_date).days > configuration.maturation_days + 1:
            as_of = max(EARLIEST_EVALUATION_DATE, last_date + timedelta(days=configuration.maturation_days + 1))
        else:
            as_of = started_at.date()
    windows = reporting_windows(as_of, configuration)
    config = configuration.snapshot()
    version = source_version(db)
    inputs = gather_inputs(db, windows)
    window_data = windows.model_dump(mode="json")
    digest = fingerprint({
        "as_of": as_of, "window": window_data, "configuration": config, "policy_version": POLICY_VERSION,
        "source_version": version, "campaigns": [asdict(item) for item in inputs],
    })
    existing = db.scalar(select(DetectionRun).where(DetectionRun.input_fingerprint == digest))
    if existing:
        return existing, True

    evaluations = []
    errors = []
    try:
        evaluations = [
            (item.campaign.id, *evaluate_campaign(item.campaign, item.observations, windows, configuration))
            for item in inputs
        ]
    except (ArithmeticError, ValueError) as error:
        logging.getLogger(__name__).error("Detection evaluation failed (%s)", type(error).__name__)
        errors.append({"code": "EVALUATION_FAILED", "message": "The run could not evaluate all campaigns."})
    run = DetectionRun(
        started_at=started_at, finished_at=datetime.now(timezone.utc), evaluation_date=as_of,
        windows=window_data, policy_version=POLICY_VERSION, configuration=config,
        input_fingerprint=digest if not errors else None, source_version=version,
        status="FAILED" if errors else "COMPLETED",
        campaign_count=len(evaluations), finding_count=sum(len(row[1]) for row in evaluations),
        suppression_count=sum(len(row[2]) for row in evaluations), errors=errors,
    )
    db.add(run)
    db.flush()
    for campaign_id, findings, suppressions in evaluations:
        for values in findings:
            values["campaign_snapshot"] = json.loads(canonical_json(values["campaign_snapshot"]))
            db.add(DetectionFinding(
                run_id=run.id, campaign_id=campaign_id,
                fingerprint=fingerprint({"campaign_id": campaign_id, **values}), **values,
            ))
        db.add_all(DetectionSuppression(run_id=run.id, campaign_id=campaign_id, **asdict(item)) for item in suppressions)
    db.flush()
    return run, False


def finding_state(run: DetectionRun, current: DetectionRun | None, version: int) -> str:
    if current is None or run.id != current.id:
        return "HISTORICAL"
    return "CURRENT" if run.source_version == version else "STALE"
