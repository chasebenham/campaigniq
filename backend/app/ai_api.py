from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.ai_analysis import (
    INTERRUPTED_MESSAGE, PENDING_LEASE, AnalysisRejection, ensure_utc, finding_is_current, finish, latest_completed, reserve,
)
from app.ai_config import AISettings, get_ai_settings
from app.ai_contract import AnalysisOutput, DetailedAnalysisOutput, LegacyAnalysisOutput, build_snapshot, cited_paths, references, validate_output
from app.ai_diagnostics import OutputRejection
from app.ai_models import AIAnalysis
from app.ai_provider import OpenAIProvider, ProviderFailure, get_ai_provider
from app.detection import fingerprint
from app.detection_api import DB, ID, require
from app.detection_models import DetectionFinding
from app.schemas import Page, PageParams

router = APIRouter(tags=["AI Analyst"])
Configuration = Annotated[AISettings, Depends(get_ai_settings)]
Provider = Annotated[OpenAIProvider, Depends(get_ai_provider)]


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegenerationRequest(EmptyRequest):
    regenerate_from: int = Field(gt=0)
    request_id: UUID


class Availability(BaseModel):
    enabled: bool
    reason: Literal["DISABLED", "MISSING_API_KEY", "PROVIDER_ERROR"] | None
    request_limit_per_hour: int
    provider_max_attempts: int
    model: str
    provider_status: Literal["UNCHECKED", "ACCESSIBLE", "ERROR"]
    provider_error_code: str | None = None
    provider_message: str | None = None


class EvidenceReference(BaseModel):
    path: str
    value: str | int | bool


class AnalysisView(BaseModel):
    id: int
    finding_id: int
    evidence_fingerprint: str
    model: str
    prompt_version: str
    schema_version: str
    status: Literal["PENDING", "COMPLETED", "STALE", "FAILED"]
    created_at: datetime
    finished_at: datetime | None
    structured_output: AnalysisOutput | DetailedAnalysisOutput | LegacyAnalysisOutput | None
    evidence_references: list[EvidenceReference]
    provider_usage: dict | None
    error_code: str | None
    error_message: str | None
    is_current: bool


def analysis_view(record: AIAnalysis, current_id: int | None) -> AnalysisView:
    expired = record.status == "PENDING" and ensure_utc(record.created_at) + PENDING_LEASE <= datetime.now(timezone.utc)
    output = record.structured_output
    values = references(record.evidence_snapshot) if output else {}
    grounded = [EvidenceReference(path=path, value=values[path]) for path in cited_paths(output)] if output else []
    return AnalysisView(
        id=record.id, finding_id=record.finding_id, evidence_fingerprint=record.evidence_fingerprint,
        model=record.model, prompt_version=record.prompt_version, schema_version=record.schema_version,
        status="FAILED" if expired else record.status, created_at=ensure_utc(record.created_at),
        finished_at=ensure_utc(record.finished_at) if record.finished_at else None,
        structured_output=output, evidence_references=grounded, provider_usage=record.provider_usage,
        error_code="AI_INTERRUPTED" if expired else record.error_code,
        error_message=INTERRUPTED_MESSAGE if expired else record.error_message,
        is_current=record.id == current_id and record.status == "COMPLETED",
    )


def current_analysis_id(db: DB, finding: DetectionFinding, settings: AISettings) -> int | None:
    if finding_is_current(db, finding):
        latest = latest_completed(db, finding.id, fingerprint(build_snapshot(finding)), settings)
        return latest.id if latest else None
    return None


def availability(settings: AISettings, provider: OpenAIProvider, *, check: bool = False) -> Availability:
    reason = settings.unavailable_reason()
    result = None if reason else provider.check(settings) if check else provider.cached_status(settings)
    return Availability(
        enabled=reason is None, reason="PROVIDER_ERROR" if result and not result.ok else reason,
        request_limit_per_hour=settings.ai_request_limit_per_hour, provider_max_attempts=settings.ai_provider_max_attempts,
        model=settings.selected_model,
        provider_status=("ACCESSIBLE" if result.ok else "ERROR") if result else "UNCHECKED",
        provider_error_code=result.code if result else None, provider_message=result.message if result else None,
    )


@router.get("/ai/status")
def status(settings: Configuration, provider: Provider) -> Availability:
    return availability(settings, provider)


@router.post("/ai/status/check")
def check_status(settings: Configuration, provider: Provider) -> Availability:
    return availability(settings, provider, check=True)


@router.post("/insights/{finding_id}/analyses", status_code=201)
def create_analysis(finding_id: ID, db: DB, settings: Configuration, provider: Provider,
                    response: Response, body: RegenerationRequest | EmptyRequest | None = None) -> AnalysisView:
    try:
        regen = body if isinstance(body, RegenerationRequest) else None
        record, reservation = reserve(db, finding_id, settings, regenerate_from=regen.regenerate_from if regen else None,
                                      request_id=str(regen.request_id) if regen else None)
    except AnalysisRejection as error:
        raise HTTPException(error.status, {"code": error.code, "message": str(error)}, headers=error.headers) from error
    if reservation is None:
        response.status_code = 202 if record.status == "PENDING" else 200
        finding = require(db, DetectionFinding, finding_id)
        result = analysis_view(record, current_analysis_id(db, finding, settings))
        db.commit()
        return result

    # The reservation and evidence snapshot are durable before any provider call.
    db.commit()
    output = usage = failure = provider_status = None
    try:
        provider_result = provider.generate(settings, reservation.snapshot)
        usage = provider_result.usage
        provider_status = provider_result.provider_status
        output = validate_output(provider_result.output, reservation.snapshot)
    except ProviderFailure as error:
        failure = error
        usage = error.usage
    except OutputRejection as error:
        failure = ProviderFailure("AI_INVALID_OUTPUT", f"The AI response failed validation ({error.diagnostic.rule}).", 502,
                                  diagnostic=error.diagnostic, provider_status=provider_status)

    record = finish(db, reservation, output, usage, failure)
    result = analysis_view(record, record.id if record.status == "COMPLETED" else None)
    db.commit()
    if failure:
        raise HTTPException(failure.status, {"code": failure.code, "message": str(failure)})
    return result


@router.get("/insights/{finding_id}/analyses")
def list_analyses(finding_id: ID, db: DB, settings: Configuration, params: Annotated[PageParams, Query()]) -> Page[AnalysisView]:
    finding = require(db, DetectionFinding, finding_id)
    current_id = current_analysis_id(db, finding, settings)
    statement = select(AIAnalysis).where(AIAnalysis.finding_id == finding_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    statement = statement.order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc()).offset(
        (params.page - 1) * params.page_size
    ).limit(params.page_size)
    return Page(
        items=[analysis_view(record, current_id) for record in db.scalars(statement)],
        page=params.page, page_size=params.page_size, total=total,
    )


@router.get("/ai/analyses/{analysis_id}")
def get_analysis(analysis_id: ID, db: DB, settings: Configuration) -> AnalysisView:
    record = require(db, AIAnalysis, analysis_id)
    finding = require(db, DetectionFinding, record.finding_id)
    return analysis_view(record, current_analysis_id(db, finding, settings))
