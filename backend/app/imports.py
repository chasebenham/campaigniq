from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from itertools import batched
import json
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.db import lock_performance_writes
from app.domain import CONTEXT_FIELDS, ImportStatus, Platform, SourceType
from app.models import Campaign, DailyCampaignPerformance, DataImport, ImportValidationError
from app.validation import NUMERIC_FIELDS, Issue, ParsedRow, parse_csv


class PreviewRow(BaseModel):
    row_number: int
    values: dict[str, str]
    status: Literal["valid", "duplicate", "rejected"]


class Preview(BaseModel):
    token: str
    total_rows: int
    valid_rows: int
    rejected_rows: int
    duplicate_rows: int
    issue_count: int
    error_counts: dict[str, int]
    rows: list[PreviewRow]
    issues: list[Issue]


@dataclass
class Assessment:
    preview: Preview
    candidates: list[ParsedRow]
    issues: list[Issue]
    campaigns: dict[tuple[str, str], Campaign]
    source_platform: str | None


class StalePreview(ValueError):
    pass


def assess(session: Session, contents: bytes) -> Assessment:
    rows = parse_csv(contents)
    clean = [row for row in rows if not row.issues]
    keys = sorted({row.campaign_key for row in clean})
    campaigns = {}
    for batch in batched(keys, 1000):
        query = select(Campaign).where(tuple_(Campaign.platform, Campaign.external_campaign_id).in_(batch))
        campaigns.update({
            (campaign.platform, campaign.external_campaign_id): campaign
            for campaign in session.scalars(query)
        })
    pairs = sorted({
        (campaigns[row.campaign_key].id, row.report_date)
        for row in clean if row.campaign_key in campaigns
    })
    existing = {}
    performance = DailyCampaignPerformance
    for batch in batched(pairs, 1000):
        query = select(performance).where(tuple_(performance.campaign_id, performance.report_date).in_(batch))
        existing.update({(row.campaign_id, row.report_date): row for row in session.scalars(query)})

    stored_contexts = defaultdict(set)
    context_columns = [getattr(performance, field) for field in CONTEXT_FIELDS]
    for batch in batched([campaign.id for campaign in campaigns.values()], 1000):
        query = select(performance.campaign_id, *context_columns).where(
            performance.campaign_id.in_(batch)
        ).distinct()
        for campaign_id, *context in session.execute(query):
            stored_contexts[campaign_id].add(tuple(context))
    file_contexts = defaultdict(set)
    for row in clean:
        file_contexts[row.campaign_key].add(row.context)

    groups = defaultdict(list)
    for row in clean:
        groups[row.key].append(row)

    outcomes = {}
    issues_by_row = {row.number: list(row.issues) for row in rows if row.issues}
    candidates = []

    def reject(row: ParsedRow, code: str, message: str, field: str | None = None):
        issues_by_row[row.number] = [
            Issue(row_number=row.number, field_name=field, error_code=code, error_message=message)
        ]

    for group in groups.values():
        first = group[0]
        campaign = campaigns.get(first.campaign_key)
        previous = stored_contexts[campaign.id] if campaign else set()
        allowed = previous or file_contexts[first.campaign_key]
        compatible = []
        for row in group:
            if len(allowed) == 1 and row.context in allowed:
                compatible.append(row)
            else:
                differences = [
                    field for index, field in enumerate(CONTEXT_FIELDS)
                    if any(context[index] != row.context[index] for context in allowed)
                ]
                reject(row, "CAMPAIGN_CONTEXT_CONFLICT", "This reporting definition conflicts with other records for this campaign.",
                       differences[0] if len(differences) == 1 else None)
        if not compatible:
            continue
        group = compatible
        first = group[0]
        persisted = existing.get((campaign.id, first.report_date)) if campaign else None
        if persisted:
            signature = tuple(getattr(persisted, field) for field in (*NUMERIC_FIELDS, *CONTEXT_FIELDS))
            for row in group:
                if row.signature == signature:
                    outcomes[row.number] = "duplicate"
                else:
                    reject(row, "EXISTING_CONFLICT", "A different record already exists for this campaign and date.")
        elif campaign and campaign.end_date and first.report_date > campaign.end_date:
            for row in group:
                reject(row, "AFTER_CAMPAIGN_END", "The date falls after this campaign's end date.", "date")
        elif any(row.signature != first.signature for row in group):
            for row in group:
                reject(row, "FILE_CONFLICT", "Multiple different records in this file share this campaign and date.")
        else:
            candidates.append(first)
            outcomes[first.number] = "valid"
            for row in group[1:]:
                outcomes[row.number] = "duplicate"

    issues = [issue for number in sorted(issues_by_row) for issue in issues_by_row[number]]
    error_counts = Counter(issue.error_code for issue in issues)
    duplicate_count = sum(status == "duplicate" for status in outcomes.values())
    platforms = {row.values["platform"] for row in rows}
    source_platform = next(iter(platforms)) if len(platforms) == 1 and platforms <= set(Platform) else None
    # Include every classification so a changed database state requires a fresh confirmation.
    manifest = [sha256(contents).hexdigest(), sorted(outcomes.items()), [issue.model_dump() for issue in issues]]
    token = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return Assessment(
        preview=Preview(
            token=token,
            total_rows=len(rows),
            valid_rows=len(candidates),
            rejected_rows=len(issues_by_row),
            duplicate_rows=duplicate_count,
            issue_count=len(issues),
            error_counts=error_counts,
            rows=[
                PreviewRow(row_number=row.number, values=row.values, status=outcomes.get(row.number, "rejected"))
                for row in rows[:25]
            ],
            issues=issues[:100],
        ),
        candidates=candidates,
        issues=issues,
        campaigns=campaigns,
        source_platform=source_platform,
    )


def commit_import(session: Session, filename: str, contents: bytes, token: str) -> DataImport:
    lock_performance_writes(session)
    assessment = assess(session, contents)
    summary = assessment.preview
    if token != summary.token:
        raise StalePreview("The file or its validation results changed. Preview it again before importing.")

    if summary.valid_rows:
        status = ImportStatus.COMPLETED_WITH_ERRORS if summary.rejected_rows else ImportStatus.COMPLETED
    else:
        status = ImportStatus.REJECTED if summary.rejected_rows else ImportStatus.NO_NEW_ROWS

    data_import = DataImport(
        filename=filename.replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "")[-255:] or "upload.csv",
        source_platform=assessment.source_platform,
        source_type=SourceType.CSV_UPLOAD,
        import_status=status,
        total_rows=summary.total_rows,
        valid_rows=summary.valid_rows,
        rejected_rows=summary.rejected_rows,
        duplicate_rows=summary.duplicate_rows,
        validation_summary={"issue_count": summary.issue_count, "error_counts": summary.error_counts},
    )
    session.add(data_import)
    session.flush()
    for row in assessment.candidates:
        campaign = assessment.campaigns.get(row.campaign_key)
        if campaign is None:
            campaign = Campaign(
                platform=row.values["platform"],
                external_campaign_id=row.values["campaign_id"],
                campaign_name=row.values["campaign_name"],
                start_date=row.report_date,
                currency="USD",
            )
            assessment.campaigns[row.campaign_key] = campaign
            session.add(campaign)
        elif row.report_date < campaign.start_date:
            campaign.start_date = row.report_date
        session.add(DailyCampaignPerformance(
            campaign=campaign,
            report_date=row.report_date,
            **row.metrics,
            **{field: row.values[field] for field in CONTEXT_FIELDS},
            source_import_id=data_import.id,
        ))
    for issue in assessment.issues:
        data_import.errors.append(ImportValidationError(**issue.model_dump()))
    return data_import
