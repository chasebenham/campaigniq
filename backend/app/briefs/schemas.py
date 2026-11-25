from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.detection_api import FindingView
from app.schemas import Page, PageParams

TEMPLATE_VERSION = "1.0.0"
MAX_FINDINGS = 8
Entity = Annotated[int, Field(gt=0, le=2**31 - 1)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
CommentaryField = Literal["executive_summary", "recommendations", "commentary", "experiment", "next_decisions"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Period(Input):
    start: date
    end: date

    @model_validator(mode="after")
    def valid_period(self):
        if not 0 <= (self.end - self.start).days < 90:
            raise ValueError("Choose an inclusive reporting period of one to 90 days.")
        if self.end >= datetime.now(timezone.utc).date():
            raise ValueError("The reporting period must end before today in UTC.")
        return self


class Selection(Input):
    finding_id: Entity
    analysis_id: Entity | None = None


class Sources(Input):
    period: Period
    findings: list[Selection] = Field(default_factory=list, max_length=MAX_FINDINGS)
    budget_id: Entity | None = None

    @model_validator(mode="after")
    def deduplicate(self):
        found = [item.finding_id for item in self.findings]
        if len(set(found)) != len(found):
            raise ValueError("Select each finding once.")
        return self


class Narrative(Input):
    executive_summary: Text = ""
    recommendations: Text = ""
    commentary: Text = ""
    next_decisions: Text = ""
    experiment: Text = ""


class EvidenceSelection(Input):
    sources: Sources
    allow_historical: bool = False
    base_version: Entity | None = None
    refresh_evidence: bool = False


class Draft(EvidenceSelection):
    title: Title
    narrative: Narrative = Field(default_factory=Narrative)
    summary_attempt_id: Entity | None = None
    commentary_attempt_ids: dict[CommentaryField, Entity] = Field(default_factory=dict)


class CommentaryRequest(EvidenceSelection):
    target: CommentaryField | Literal["all"]
    request_id: UUID
    brief_id: Entity | None = None


class CommentaryProvenance(BaseModel):
    id: int
    model: str
    prompt_version: str
    schema_version: str
    evidence_fingerprint: Digest
    generated_at: datetime
    usage: dict | None
    references: list[str]
    authorship: Literal["AI_GENERATED", "AI_EDITED_BY_MANAGEMENT"]
    stale: bool = False


class CommentaryResult(BaseModel):
    fields: dict[CommentaryField, str]
    provenance: dict[CommentaryField, CommentaryProvenance]


class Save(Draft):
    evidence_fingerprint: Digest


class Table(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    caption: str | None = None


class Block(BaseModel):
    title: str | None = None
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    source: Literal["verified", "ai", "management", "modeled"] | None = None


class Section(BaseModel):
    title: str
    blocks: list[Block]


class Document(BaseModel):
    title: str
    period: Period
    generated_at: datetime
    template_version: str = TEMPLATE_VERSION
    provenance: str
    sections: list[Section]


class Preview(BaseModel):
    document: Document
    evidence_fingerprint: Digest
    warnings: list[str]


class BriefSummary(BaseModel):
    id: int
    title: str
    period: Period
    current_version: int
    created_at: datetime
    updated_at: datetime
    status: Literal["SAVED"] = "SAVED"
    freshness: Literal["CURRENT", "STALE"]


class VersionSummary(BaseModel):
    version: int
    title: str
    period: Period
    generated_at: datetime
    evidence_fingerprint: Digest
    template_version: str


class SummaryProposal(BaseModel):
    id: int
    version: int
    status: Literal["PENDING", "COMPLETED", "FAILED", "STALE"]
    model: str
    text: str | None = None
    references: list[str] = Field(default_factory=list)
    usage: dict | None = None
    error: str | None = None


class VersionView(VersionSummary):
    brief_id: int
    current_version: int
    freshness: Literal["CURRENT", "STALE"]
    draft: Draft
    document: Document
    warnings: list[str]
    generation: SummaryProposal | None = None
    commentary_provenance: dict[CommentaryField, CommentaryProvenance] = Field(default_factory=dict)


class Defaults(BaseModel):
    period: Period | None
    suggested_run_id: int | None


class OptionsParams(PageParams):
    start: date
    end: date

    @model_validator(mode="after")
    def check_dates(self):
        Period(start=self.start, end=self.end)
        return self


class AnalysisOption(BaseModel):
    id: int
    model: str
    created_at: datetime
    historical: bool


class FindingOption(BaseModel):
    finding: FindingView
    analyses: list[AnalysisOption]
    suggested: bool


class Options(BaseModel):
    suggested_run_id: int | None
    findings: Page[FindingOption]
