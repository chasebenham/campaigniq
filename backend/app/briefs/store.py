"""Version and retrieve executive report snapshots."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_analysis import INTERRUPTED_MESSAGE, PENDING_LEASE, ensure_utc
from app.brief_models import BriefSummaryAttempt, StrategyBrief, StrategyBriefVersion
from app.briefs.document import make_document
from app.briefs.evidence import collect, error, evidence_fingerprint
from app.briefs.schemas import BriefSummary, Document, Draft, EvidenceSelection, Period, Preview, Save, Sources, SummaryProposal, VersionSummary, VersionView
from app.db import lock_performance_writes


def utc_now():
    return datetime.now(timezone.utc)


def get_brief(db: Session, brief_id: int):
    row = db.get(StrategyBrief, brief_id)
    if row is None:
        raise error(404, "BRIEF_NOT_FOUND", "The strategy brief could not be found.")
    return row


def get_version(db: Session, brief: StrategyBrief, version: int | None = None):
    number = brief.current_version if version is None else version
    row = db.scalar(select(StrategyBriefVersion).where(
        StrategyBriefVersion.brief_id == brief.id, StrategyBriefVersion.version == number))
    if row is None:
        raise error(404, "BRIEF_VERSION_NOT_FOUND", "The requested report version could not be found.")
    return row


def freshness(db: Session, row: StrategyBriefVersion):
    try:
        current = collect(db, Sources.model_validate(row.sources), allow_historical=True)
    except HTTPException:
        return "STALE"
    return "CURRENT" if evidence_fingerprint(current) == row.evidence_fingerprint else "STALE"


def generation_view(record: BriefSummaryAttempt, row: StrategyBriefVersion) -> SummaryProposal:
    output = record.output or {}
    expired = record.status == "PENDING" and ensure_utc(record.created_at) + PENDING_LEASE <= utc_now()
    return SummaryProposal(id=record.id, version=row.version, status="FAILED" if expired else record.status, model=record.model,
                           text=output.get("summary"), references=output.get("references", []),
                           usage=record.usage, error=INTERRUPTED_MESSAGE if expired else record.error)


def latest_generation(db: Session, row: StrategyBriefVersion) -> SummaryProposal | None:
    query = select(BriefSummaryAttempt).where(BriefSummaryAttempt.version_id == row.id)
    record = db.scalar(query.order_by(BriefSummaryAttempt.id.desc()).limit(1))
    return generation_view(record, row) if record else None


def summarize(db: Session, brief: StrategyBrief) -> BriefSummary:
    row = get_version(db, brief)
    return BriefSummary(id=brief.id, title=brief.title, period=Period(start=brief.reporting_start, end=brief.reporting_end),
                        current_version=brief.current_version, updated_at=ensure_utc(brief.updated_at),
                        created_at=ensure_utc(brief.created_at), freshness=freshness(db, row))


def version_summary(row: StrategyBriefVersion) -> VersionSummary:
    return VersionSummary(version=row.version, title=row.title, period=Period.model_validate(row.sources["period"]),
                          generated_at=ensure_utc(row.generated_at), evidence_fingerprint=row.evidence_fingerprint,
                          template_version=row.template_version)


def version_view(db: Session, brief: StrategyBrief, row: StrategyBriefVersion) -> VersionView:
    already_historical = any(item["finding"]["state"] != "CURRENT" or
                             bool(item["analysis"] and item["analysis"]["historical"]) for item in row.evidence["findings"])
    if row.evidence["budget"]:
        already_historical = already_historical or row.evidence["budget"]["status"] == "STALE"
    metadata = row.generation_metadata or {}
    summary = metadata.get("summary") if "commentary" in metadata else metadata
    commentary = metadata.get("commentary", {})
    return VersionView(
        **version_summary(row).model_dump(), brief_id=brief.id, current_version=brief.current_version,
        freshness=freshness(db, row), document=Document.model_validate(row.document), warnings=row.evidence["warnings"],
        draft=Draft(title=row.title, sources=row.sources, narrative=row.narrative, base_version=row.version,
                    summary_attempt_id=summary.get("id") if summary else None,
                    commentary_attempt_ids={key: item["id"] for key, item in commentary.items()},
                    allow_historical=already_historical),
        generation=latest_generation(db, row),
        commentary_provenance=commentary,
    )


def proposed_metadata(db: Session, draft: Draft, brief: StrategyBrief | None, digest: str) -> dict | None:
    if draft.summary_attempt_id is None or not draft.narrative.executive_summary or "executive_summary" in draft.commentary_attempt_ids:
        return None
    attempt = db.get(BriefSummaryAttempt, draft.summary_attempt_id)
    parent = db.get(StrategyBriefVersion, attempt.version_id) if attempt else None
    if not (attempt and brief and parent and parent.brief_id == brief.id and attempt.status == "COMPLETED" and attempt.output):
        raise error(422, "INVALID_SUMMARY_PROPOSAL", "Use a completed summary proposal tied to this brief.")
    return {
        "id": attempt.id, "model": attempt.model, "prompt_version": attempt.prompt_version,
        "schema_version": attempt.schema_version, "evidence_fingerprint": attempt.evidence_fingerprint,
        "stale": attempt.evidence_fingerprint != digest,
        "usage": attempt.usage, "references": attempt.output["references"],
        "authorship": ("AI_GENERATED" if draft.narrative.executive_summary == attempt.output["summary"]
                       else "AI_EDITED_BY_MANAGEMENT"),
    }


def select_evidence(db: Session, draft: EvidenceSelection, brief: StrategyBrief | None) -> dict:
    if brief:
        if draft.base_version != brief.current_version:
            raise error(409, "VERSION_CONFLICT", "This report has a newer version. Open it before saving another revision.")
        parent = get_version(db, brief)
        if not draft.refresh_evidence and draft.sources == Sources.model_validate(parent.sources):
            return parent.evidence
    elif draft.base_version is not None or draft.refresh_evidence:
        raise error(422, "INVALID_REVISION", "Create a report before requesting a revision.")
    return collect(db, draft.sources, allow_historical=draft.allow_historical)


def provenance(attempt: BriefSummaryAttempt, field: str, content: str, digest: str) -> dict:
    item = attempt.output["fields"][field]
    return {
        "id": attempt.id, "model": attempt.model, "prompt_version": attempt.prompt_version,
        "schema_version": attempt.schema_version, "evidence_fingerprint": attempt.evidence_fingerprint,
        "generated_at": ensure_utc(attempt.finished_at).isoformat(), "usage": attempt.usage,
        "references": item["references"],
        "stale": attempt.evidence_fingerprint != digest or bool(attempt.output.get("snapshot_stale")),
        "authorship": "AI_GENERATED" if content == item["text"] else "AI_EDITED_BY_MANAGEMENT",
    }


def prepare(db: Session, draft: Draft, brief: StrategyBrief | None = None) -> tuple[Preview, dict, dict | None]:
    evidence = select_evidence(db, draft, brief)
    digest = evidence_fingerprint(evidence)
    generation = proposed_metadata(db, draft, brief, digest)
    commentary = {}
    for field, attempt_id in draft.commentary_attempt_ids.items():
        if not (content := getattr(draft.narrative, field)):
            continue
        attempt = db.get(BriefSummaryAttempt, attempt_id)
        if not (attempt and attempt.request_key and attempt.status == "COMPLETED"
                and attempt.finished_at and field in (attempt.output or {}).get("fields", {})):
            raise error(422, "INVALID_COMMENTARY_DRAFT", "Choose a validated AI draft for the corresponding commentary field.")
        commentary[field] = provenance(attempt, field, content, digest)
    metadata = {"summary": generation, "commentary": commentary} if commentary else generation
    document = make_document(draft, evidence, utc_now(), generation, commentary)
    return Preview(document=document, evidence_fingerprint=digest, warnings=evidence["warnings"]), evidence, metadata


def save_version(db: Session, draft: Save, brief_id: int | None = None) -> VersionView:
    lock_performance_writes(db)
    brief = get_brief(db, brief_id) if brief_id else None
    preview, evidence, generation = prepare(db, draft, brief)
    if draft.evidence_fingerprint != preview.evidence_fingerprint:
        raise error(409, "EVIDENCE_CHANGED", "Evidence changed. Preview the report again before saving.")
    stamp = preview.document.generated_at
    period = draft.sources.period
    if not brief:
        brief = StrategyBrief(title=draft.title, reporting_start=period.start, reporting_end=period.end,
                              current_version=1, created_at=stamp, updated_at=stamp)
        db.add(brief)
        db.flush()
    else:
        brief.title, brief.reporting_start, brief.reporting_end = draft.title, period.start, period.end
        brief.current_version += 1
        brief.updated_at = stamp
    row = StrategyBriefVersion(
        brief_id=brief.id, version=brief.current_version, title=draft.title, generated_at=stamp,
        evidence_fingerprint=preview.evidence_fingerprint, template_version=preview.document.template_version,
        budget_scenario_id=draft.sources.budget_id, sources=draft.sources.model_dump(mode="json"),
        narrative=draft.narrative.model_dump(mode="json"), evidence=evidence,
        document=preview.document.model_dump(mode="json"), generation_metadata=generation,
    )
    db.add(row)
    db.flush()
    result = version_view(db, brief, row)
    db.commit()
    return result
