from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, union_all, update
from sqlalchemy.orm import Session

from app.ai_config import AISettings
from app.ai_contract import AnalysisOutput, MAX_EVIDENCE_BYTES, PROMPT_VERSION, SCHEMA_VERSION, build_snapshot, provider_payload
from app.ai_diagnostics import diagnostic_artifact
from app.ai_models import AIAnalysis
from app.ai_provider import ProviderFailure
from app.brief_models import BriefSummaryAttempt
from app.db import lock_performance_writes
from app.detection import active_run, canonical_json, finding_state, fingerprint, source_version
from app.detection_models import DetectionFinding, DetectionRun

PENDING_LEASE = timedelta(seconds=90)
RATE_WINDOW = timedelta(hours=1)
INTERRUPTED_MESSAGE = "The previous request did not finish. You can retry."


class AnalysisRejection(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.headers = headers


@dataclass(frozen=True)
class Reservation:
    id: int
    snapshot: dict


def finding_is_current(db: Session, finding: DetectionFinding) -> bool:
    run = db.get(DetectionRun, finding.run_id)
    return bool(run and finding_state(run, active_run(db), source_version(db)) == "CURRENT")


def matching_attempts(finding_id: int, digest: str, settings: AISettings):
    ai = AIAnalysis
    return select(ai).where(
        ai.finding_id == finding_id, ai.evidence_fingerprint == digest, ai.model == settings.selected_model,
        ai.prompt_version == PROMPT_VERSION, ai.schema_version == SCHEMA_VERSION,
    )


def latest_completed(db: Session, finding_id: int, digest: str, settings: AISettings) -> AIAnalysis | None:
    return db.scalar(matching_attempts(finding_id, digest, settings).where(AIAnalysis.status == "COMPLETED")
                     .order_by(AIAnalysis.id.desc()).limit(1))


def reserve(db: Session, finding_id: int, settings: AISettings, *, regenerate_from: int | None = None,
            request_id: str | None = None) -> tuple[AIAnalysis, Reservation | None]:
    if reason := settings.unavailable_reason():
        message = "AI analysis is disabled on the server." if reason == "DISABLED" else "Configure an OpenAI API key on the server."
        raise AnalysisRejection(503, f"AI_{reason}", message)
    lock_performance_writes(db)
    finding = db.get(DetectionFinding, finding_id)
    if finding is None:
        raise AnalysisRejection(404, "NOT_FOUND", "The requested finding could not be found.")
    if not finding_is_current(db, finding):
        raise AnalysisRejection(409, "AI_STALE_EVIDENCE", "Run performance analysis and choose a current finding.")

    snapshot = build_snapshot(finding)
    if len(canonical_json(provider_payload(snapshot)).encode()) > MAX_EVIDENCE_BYTES:
        raise AnalysisRejection(422, "AI_EVIDENCE_TOO_LARGE", "This finding exceeds the AI evidence size limit.")
    digest = fingerprint(snapshot)
    now = datetime.now(timezone.utc)
    ai = AIAnalysis
    # Release a reservation after a crashed worker or a hung request.
    db.execute(update(ai).where(ai.status == "PENDING", ai.created_at <= now - PENDING_LEASE).values(
        status="FAILED", finished_at=now, error_code="AI_INTERRUPTED", error_message=INTERRUPTED_MESSAGE,
    ))
    if request_id and (replay := db.scalar(select(ai).where(ai.finding_id == finding_id, ai.request_id == request_id))):
        return replay, None
    pending = db.scalar(matching_attempts(finding_id, digest, settings).where(ai.status == "PENDING"))
    if pending:
        return pending, None
    completed = latest_completed(db, finding_id, digest, settings)
    if regenerate_from is None:
        if completed:
            return completed, None
    else:
        original = db.scalar(matching_attempts(finding_id, digest, settings).where(
            ai.id == regenerate_from, ai.status == "COMPLETED",
        ))
        if original is None:
            raise AnalysisRejection(409, "AI_REGENERATION_CONFLICT", "Refresh and select the current completed analysis before regenerating.")
        if completed and completed.id != original.id:
            return completed, None

    check_rate_limit(db, settings, now)

    record = AIAnalysis(
        finding_id=finding.id, evidence_fingerprint=digest, evidence_snapshot=snapshot,
        model=settings.selected_model, prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION, request_id=request_id,
        status="PENDING", created_at=now,
    )
    db.add(record)
    db.flush()
    return record, Reservation(record.id, snapshot)


def finish(db: Session, reservation: Reservation, output: AnalysisOutput | None, usage: dict | None,
           failure: ProviderFailure | None) -> AIAnalysis:
    lock_performance_writes(db)
    record = db.get(AIAnalysis, reservation.id)
    if record.status != "PENDING":
        return record
    record.finished_at = datetime.now(timezone.utc)
    record.provider_usage = usage
    if failure is not None:
        record.status = "FAILED"
        record.error_code = failure.code
        record.error_message = str(failure)
        record.validation_diagnostic = diagnostic_artifact(
            failure.diagnostic, status=failure.provider_status, schema_version=record.schema_version,
            evidence_fingerprint=record.evidence_fingerprint, attempt_id=record.id,
        )
    else:
        finding = db.get(DetectionFinding, record.finding_id)
        matches = (
            finding is not None
            and record.evidence_fingerprint == fingerprint(reservation.snapshot) == fingerprint(build_snapshot(finding))
            and finding_is_current(db, finding)
        )
        record.structured_output = output.model_dump(mode="json")
        if matches:
            record.status = "COMPLETED"
        else:
            record.status = "STALE"
            record.error_code = "AI_STALE_EVIDENCE"
            record.error_message = "The reporting evidence changed while this analysis was running."
    db.flush()
    return record


def check_rate_limit(db: Session, settings: AISettings, now: datetime) -> None:
    recent = union_all(*(select(model.created_at).where(model.created_at > now - RATE_WINDOW)
                         for model in (AIAnalysis, BriefSummaryAttempt))).subquery()
    count, oldest = db.execute(select(func.count(), func.min(recent.c.created_at))).one()
    if count >= settings.ai_request_limit_per_hour:
        retry = max(1, int((ensure_utc(oldest) + RATE_WINDOW - now).total_seconds()) + 1)
        raise AnalysisRejection(429, "AI_RATE_LIMIT", "The workspace has reached its hourly AI request limit. Try again later.",
                                {"Retry-After": str(retry)})


def ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
