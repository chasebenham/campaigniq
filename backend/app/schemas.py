from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import CampaignStatus, ImportStatus, Platform, SourceType
from app.metrics import Metrics
from app.validation import Issue


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date | None = None
    end_date: date | None = None
    platform: Platform | None = None
    campaign_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date must be on or before end date.")
        return self


class CampaignFilters(Filters):
    status: CampaignStatus | None = None
    sort: Literal[
        "campaign_name", "platform", "status", "spend", "clicks", "attributed_purchases",
        "cpa", "roas", "target_cpa", "target_roas", "first_date", "last_date",
    ] = "spend"
    direction: Literal["asc", "desc"] = "desc"
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=25, ge=1, le=100)


class PageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=25, ge=1, le=100)


class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int


class CampaignOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: Platform
    campaign_name: str


class CampaignMetadata(CampaignOption):
    external_campaign_id: str
    objective: str
    status: CampaignStatus
    target_cpa: Decimal | None
    target_roas: Decimal | None
    currency: str
    start_date: date
    end_date: date | None
    created_at: datetime
    updated_at: datetime


class Attribution(BaseModel):
    conversion_action: str
    attribution_method: str
    attribution_window: str
    date_basis: str


class Report(BaseModel):
    metrics: Metrics | None
    first_date: date | None
    last_date: date | None
    latest_import_at: datetime | None
    record_count: int
    fictional_record_count: int
    observed_days: int
    attribution_contexts: list[Attribution]
    conversion_status: Literal["available", "incompatible", "unavailable", "empty"]
    platform_attributed_overlap: bool


class PlatformReport(Report):
    platform: Platform


class CampaignReport(CampaignMetadata):
    report: Report
    missing_days: int | None
    cpa_target_status: Literal["met", "missed"] | None
    roas_target_status: Literal["met", "missed"] | None


class TrendPoint(BaseModel):
    date: date
    metrics: Metrics


class TrendReport(BaseModel):
    items: list[TrendPoint]
    first_date: date | None
    last_date: date | None


class CampaignPerformance(CampaignReport):
    trends: TrendReport


class ImportRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    source_platform: Platform | None
    imported_at: datetime
    total_rows: int
    valid_rows: int
    rejected_rows: int
    duplicate_rows: int
    import_status: ImportStatus
    validation_summary: dict
    source_type: SourceType


class ImportDetails(ImportRecord):
    issues: Page[Issue]
