from typing import Annotated

from fastapi import (
    APIRouter, Depends, FastAPI, File, Form, HTTPException, Path, Query, UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import analytics
from app.ai_api import router as ai_router
from app.config import Settings
from app.db import get_db
from app.detection_api import router as detection_router
from app.imports import Preview, StalePreview, assess, commit_import
from app.models import Campaign, DataImport, ImportValidationError
from app.schemas import (
    CampaignFilters, CampaignMetadata, CampaignOption, CampaignPerformance, CampaignReport, Filters,
    ImportDetails, ImportRecord, Page, PageParams, PlatformReport, Report, TrendReport,
)
from app.validation import MAX_FILE_BYTES, InvalidCSV, Issue

app = FastAPI(title="CampaignIQ", version="1.0.0", description="Northstar Outfitters performance analytics")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[Settings().frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
api = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]
ReportFilters = Annotated[Filters, Query()]
CampaignQuery = Annotated[CampaignFilters, Query()]
Pagination = Annotated[PageParams, Query()]
EntityID = Annotated[int, Path(gt=0)]
CSVFile = Annotated[UploadFile, File(description="UTF-8 canonical CampaignIQ CSV")]


def error_response(status: int, code: str, message: str, details=None, headers=None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request, error):
    detail = error.detail
    return error_response(
        error.status_code,
        detail.get("code", "HTTP_ERROR") if isinstance(detail, dict) else "HTTP_ERROR",
        detail.get("message", "The request could not be completed.") if isinstance(detail, dict) else str(detail),
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request, error):
    details = [{"location": list(item["loc"]), "message": item["msg"]} for item in error.errors()]
    return error_response(422, "INVALID_REQUEST", "; ".join(item["message"] for item in details), details)


@app.exception_handler(InvalidCSV)
async def handle_csv_error(request, error):
    status = 413 if error.code == "FILE_TOO_LARGE" else 422
    return error_response(status, error.code, str(error))


@app.exception_handler(StalePreview)
async def handle_stale_preview(request, error):
    return error_response(409, "STALE_PREVIEW", str(error))


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(request, error):
    import logging
    logging.getLogger(__name__).error("Database request failed (%s)", type(error).__name__)
    return error_response(503, "DATABASE_ERROR", "The database could not complete the request. Try again shortly.")


def find_record(db: Session, model, record_id: int):
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "The requested record could not be found."})
    return record


@api.get("/health", tags=["System"])
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@api.get("/campaigns", tags=["Campaigns"])
@api.get("/analytics/campaigns", tags=["Analytics"])
def get_campaigns(db: DB, filters: CampaignQuery) -> Page[CampaignReport]:
    return analytics.campaign_reports(db, filters)


@api.get("/campaign-options", tags=["Campaigns"])
def get_campaign_options(db: DB, pagination: Pagination) -> Page[CampaignOption]:
    total = db.scalar(select(func.count(Campaign.id))) or 0
    query = select(Campaign).order_by(Campaign.campaign_name, Campaign.id).offset(
        (pagination.page - 1) * pagination.page_size
    ).limit(pagination.page_size)
    return Page(
        items=[CampaignOption.model_validate(campaign) for campaign in db.scalars(query)],
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@api.get("/campaigns/{campaign_id}", tags=["Campaigns"])
def get_campaign(campaign_id: EntityID, db: DB) -> CampaignMetadata:
    return CampaignMetadata.model_validate(find_record(db, Campaign, campaign_id))


@api.get("/campaigns/{campaign_id}/performance", tags=["Campaigns"])
def get_campaign_performance(campaign_id: EntityID, db: DB, filters: ReportFilters) -> CampaignPerformance:
    campaign = find_record(db, Campaign, campaign_id)
    if filters.campaign_id is not None and filters.campaign_id != campaign_id:
        raise HTTPException(422, {"code": "CAMPAIGN_FILTER_MISMATCH", "message": "Campaign filter must match the path."})
    filters = filters.model_copy(update={"campaign_id": campaign_id})
    buckets = analytics.performance_buckets(db, filters)
    return CampaignPerformance(
        **analytics.campaign_report(campaign, buckets, filters).model_dump(), trends=analytics.trends(buckets)
    )


@api.get("/analytics/overview", tags=["Analytics"])
def overview(db: DB, filters: ReportFilters) -> Report:
    return analytics.summarize(analytics.performance_buckets(db, filters))


@api.get("/analytics/trends", tags=["Analytics"])
def get_trends(db: DB, filters: ReportFilters) -> TrendReport:
    return analytics.trends(analytics.performance_buckets(db, filters))


@api.get("/analytics/platforms", tags=["Analytics"])
def get_platforms(db: DB, filters: ReportFilters) -> list[PlatformReport]:
    return analytics.platforms(analytics.performance_buckets(db, filters))


def read_upload(file: UploadFile) -> bytes:
    return file.file.read(MAX_FILE_BYTES + 1)


@api.post("/imports/preview", tags=["Imports"])
def preview_file(db: DB, file: CSVFile) -> Preview:
    return assess(db, read_upload(file)).preview


@api.post("/imports/commit", tags=["Imports"], status_code=201)
def import_file(
    db: DB, file: CSVFile,
    preview_token: Annotated[str, Form(pattern=r"^[a-f0-9]{64}$")],
) -> ImportRecord:
    record = commit_import(db, file.filename or "upload.csv", read_upload(file), preview_token)
    db.flush()
    result = ImportRecord.model_validate(record)
    db.commit()
    return result


@api.get("/imports", tags=["Imports"])
def list_imports(db: DB, pagination: Pagination) -> Page[ImportRecord]:
    total = db.scalar(select(func.count(DataImport.id))) or 0
    query = (
        select(DataImport).order_by(DataImport.imported_at.desc(), DataImport.id.desc())
        .offset((pagination.page - 1) * pagination.page_size).limit(pagination.page_size)
    )
    return Page(
        items=[ImportRecord.model_validate(record) for record in db.scalars(query)],
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@api.get("/imports/{import_id}", tags=["Imports"])
def get_import(import_id: EntityID, db: DB, pagination: Pagination) -> ImportDetails:
    record = find_record(db, DataImport, import_id)
    issues = select(ImportValidationError).where(ImportValidationError.import_id == import_id)
    total = db.scalar(select(func.count()).select_from(issues.subquery())) or 0
    issues = issues.order_by(ImportValidationError.row_number, ImportValidationError.id).offset(
        (pagination.page - 1) * pagination.page_size
    ).limit(pagination.page_size)
    return ImportDetails(
        **ImportRecord.model_validate(record).model_dump(),
        issues=Page(
            items=[Issue.model_validate(issue, from_attributes=True) for issue in db.scalars(issues)],
            page=pagination.page, page_size=pagination.page_size, total=total,
        ),
    )


api.include_router(detection_router)
api.include_router(ai_router)
app.include_router(api)
