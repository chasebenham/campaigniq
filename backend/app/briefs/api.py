from typing import Annotated

from fastapi import APIRouter, Path, Query, Response
from pydantic import Field
from sqlalchemy import func, select

from app.ai_api import Configuration, Provider
from app.brief_models import StrategyBrief, StrategyBriefVersion
from app.briefs.commentary import generate_commentary
from app.briefs.evidence import defaults, finding_options
from app.briefs.pdf import filename, render_pdf
from app.briefs.schemas import (
    BriefSummary, CommentaryRequest, CommentaryResult, Defaults, Document, Draft, Input, Options, OptionsParams, Preview, Save,
    SummaryProposal, VersionSummary, VersionView,
)
from app.briefs.store import get_brief, get_version, prepare, save_version, summarize, version_summary, version_view
from app.briefs.synthesis import generate
from app.detection_api import DB
from app.schemas import Page, PageParams

router = APIRouter(prefix="/strategy-briefs", tags=["Strategy Briefs"])
ID = Annotated[int, Path(gt=0, le=2**31 - 1)]


class BriefPages(PageParams):
    page_size: int = Field(default=8, ge=1, le=12)


class GenerateRequest(Input):
    version: int = Field(gt=0, le=2**31 - 1)


@router.get("/defaults")
def brief_defaults(db: DB) -> Defaults:
    return defaults(db)


@router.get("/sources")
def sources(db: DB, params: Annotated[OptionsParams, Query()]) -> Options:
    return finding_options(db, params)


@router.post("/preview")
def preview(draft: Draft, db: DB) -> Preview:
    return prepare(db, draft)[0]


@router.post("/draft-commentary")
def draft_commentary(body: CommentaryRequest, db: DB, settings: Configuration, provider: Provider) -> CommentaryResult:
    return generate_commentary(db, body, settings, provider)


@router.post("/{brief_id}/preview")
def preview_revision(brief_id: ID, draft: Draft, db: DB) -> Preview:
    return prepare(db, draft, get_brief(db, brief_id))[0]


@router.get("")
def briefs(db: DB, paging: Annotated[BriefPages, Query()]) -> Page[BriefSummary]:
    query = select(StrategyBrief).order_by(StrategyBrief.updated_at.desc(), StrategyBrief.id.desc())
    total = db.scalar(select(func.count(StrategyBrief.id))) or 0
    rows = db.scalars(query.offset((paging.page - 1) * paging.page_size).limit(paging.page_size))
    return Page(items=[summarize(db, row) for row in rows], page=paging.page, page_size=paging.page_size, total=total)


@router.post("", status_code=201)
def create(draft: Save, db: DB) -> VersionView:
    return save_version(db, draft)


@router.get("/{brief_id}")
def read(brief_id: ID, db: DB) -> VersionView:
    brief = get_brief(db, brief_id)
    return version_view(db, brief, get_version(db, brief))


@router.put("/{brief_id}", status_code=201)
def revise(brief_id: ID, draft: Save, db: DB) -> VersionView:
    return save_version(db, draft, brief_id)


@router.get("/{brief_id}/versions")
def versions(brief_id: ID, db: DB, paging: Annotated[PageParams, Query()]) -> Page[VersionSummary]:
    get_brief(db, brief_id)
    query = select(StrategyBriefVersion).where(StrategyBriefVersion.brief_id == brief_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(StrategyBriefVersion.version.desc())
                      .offset((paging.page - 1) * paging.page_size).limit(paging.page_size))
    return Page(items=[version_summary(row) for row in rows], page=paging.page, page_size=paging.page_size, total=total)


@router.get("/{brief_id}/versions/{version}")
def read_version(brief_id: ID, version: ID, db: DB) -> VersionView:
    brief = get_brief(db, brief_id)
    return version_view(db, brief, get_version(db, brief, version))


@router.post("/{brief_id}/generate-summary")
def summary(brief_id: ID, body: GenerateRequest, db: DB, settings: Configuration, provider: Provider) -> SummaryProposal:
    return generate(db, brief_id, body.version, settings, provider)


@router.get("/{brief_id}/export/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
def export(brief_id: ID, db: DB, version: Annotated[int, Query(gt=0, le=2**31 - 1)]) -> Response:
    row = get_version(db, get_brief(db, brief_id), version)
    return Response(
        render_pdf(Document.model_validate(row.document), row.version), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename(row.title, row.version)}"'},
    )
