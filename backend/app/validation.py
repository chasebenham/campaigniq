import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.domain import CANONICAL_CONTEXT, CONTEXT_FIELDS, CONTEXT_OPTIONS, Platform, ReportingContext

CSV_COLUMNS = (
    "date", "platform", "campaign_id", "campaign_name", "impressions", "clicks", "spend",
    "attributed_purchases", "attributed_purchase_value", *CONTEXT_FIELDS, "currency",
)
MAX_ROWS = 20_000
MAX_FILE_BYTES = 5 * 1024 * 1024
NUMERIC_FIELDS = {
    "impressions": (19, 0),
    "clicks": (19, 0),
    "spend": (14, 4),
    "attributed_purchases": (12, 6),
    "attributed_purchase_value": (14, 4),
}
IDENTIFIER_LIMITS = {"campaign_id": 100, "campaign_name": 180}


class Issue(BaseModel):
    row_number: int
    field_name: str | None = None
    error_code: str
    error_message: str


class InvalidCSV(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedRow:
    number: int
    values: dict[str, str]
    report_date: date | None
    metrics: dict[str, int | Decimal]
    issues: list[Issue]

    @property
    def campaign_key(self):
        return self.values["platform"], self.values["campaign_id"]

    @property
    def key(self):
        return (*self.campaign_key, self.report_date)

    @property
    def signature(self):
        return tuple(self.metrics[name] for name in NUMERIC_FIELDS) + self.context

    @property
    def context(self) -> tuple[str, ...]:
        return tuple(self.values[name] for name in CONTEXT_FIELDS)


def validate_row(number: int, values: dict[str, str], extra_columns: bool) -> ParsedRow:
    issues: list[Issue] = []

    def add(field: str | None, code: str, message: str):
        issues.append(Issue(row_number=number, field_name=field, error_code=code, error_message=message))

    if extra_columns:
        add(None, "COLUMN_COUNT", "This row has more values than the header.")
    for field in CSV_COLUMNS:
        if not values[field]:
            add(field, "REQUIRED", f"{field} is required.")
        elif any(ord(char) < 32 for char in values[field]):
            add(field, "CONTROL_CHARACTER", f"{field} contains a control character.")
    for field, limit in IDENTIFIER_LIMITS.items():
        if len(values[field]) > limit:
            add(field, "TOO_LONG", f"{field} must be at most {limit} characters.")

    report_date = None
    if values["date"]:
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", values["date"]):
                raise ValueError
            report_date = date.fromisoformat(values["date"])
        except ValueError:
            add("date", "INVALID_DATE", "Use a valid calendar date in YYYY-MM-DD format.")
    if values["platform"] and values["platform"] not in set(Platform):
        add("platform", "UNSUPPORTED_PLATFORM", "Use GOOGLE_ADS or META_ADS.")
    if values["currency"] and values["currency"] != "USD":
        add("currency", "UNSUPPORTED_CURRENCY", "CampaignIQ currently accepts USD only.")

    metrics: dict[str, int | Decimal] = {}
    for field, (whole_limit, scale) in NUMERIC_FIELDS.items():
        raw = values[field]
        if not raw:
            continue
        pattern = r"-?[0-9]+(?:\.[0-9]+)?" if scale else r"-?[0-9]+"
        if len(raw) > 100 or not re.fullmatch(pattern, raw):
            add(field, "INVALID_NUMBER", f"{field} must be a plain {'decimal' if scale else 'integer'}.")
            continue
        whole, _, fraction = raw.lstrip("-").partition(".")
        if len(whole.lstrip("0")) > whole_limit or len(fraction) > scale:
            add(field, "NUMERIC_PRECISION", f"{field} supports {whole_limit} whole digits and {scale} decimal places.")
            continue
        value = Decimal(raw) if scale else int(raw)
        if value < 0:
            add(field, "NEGATIVE_NUMBER", f"{field} must be nonnegative.")
        elif not scale and value > 2**63 - 1:
            add(field, "NUMERIC_RANGE", f"{field} exceeds the supported integer range.")
        else:
            metrics[field] = value
    if "clicks" in metrics and "impressions" in metrics and metrics["clicks"] > metrics["impressions"]:
        add("clicks", "CLICKS_EXCEED_IMPRESSIONS", "Clicks cannot exceed impressions in this schema.")

    metadata_valid = True
    for field, supported in CONTEXT_OPTIONS.items():
        if values[field] not in supported:
            metadata_valid = False
            if values[field]:
                add(field, "UNRECOGNIZED_DEFINITION", f"Use one of: {', '.join(sorted(supported))}.")
    if metadata_valid:
        context = ReportingContext(*(values[field] for field in CONTEXT_FIELDS))
        for field in CONTEXT_FIELDS:
            expected = getattr(CANONICAL_CONTEXT, field)
            actual = getattr(context, field)
            if field == "attribution_method" and actual in {"LAST_CLICK", "DATA_DRIVEN", "LINEAR"}:
                continue
            if actual != expected:
                add(field, "INCOMPATIBLE_CONTEXT", f"This workspace requires {expected} for {field}.")
        if context.attribution_method == "LAST_CLICK" and (purchases := metrics.get("attributed_purchases")) is not None:
            if purchases != int(purchases):
                add("attributed_purchases", "FRACTIONAL_LAST_CLICK", "Last-click purchase credit must be a whole number.")

    return ParsedRow(number, values, report_date, metrics, issues)


def parse_csv(contents: bytes) -> list[ParsedRow]:
    if len(contents) > MAX_FILE_BYTES:
        raise InvalidCSV("FILE_TOO_LARGE", "Select a CSV of at most 5 MiB.")
    try:
        source = contents.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidCSV("INVALID_ENCODING", "Save the CSV as UTF-8.") from error

    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    try:
        headers = [value.strip().lower() for value in next(reader, [])]
        missing = sorted(set(CSV_COLUMNS) - set(headers))
        if missing:
            raise InvalidCSV("MISSING_COLUMNS", f"Missing columns: {', '.join(missing)}.")
        if len(headers) != len(set(headers)) or "" in headers:
            raise InvalidCSV("INVALID_HEADERS", "Headers must be nonempty and unique.")
        rows = []
        while True:
            number = reader.line_num + 1
            raw = next(reader, None)
            if raw is None:
                break
            if not raw or not any(value.strip() for value in raw):
                continue
            if len(rows) >= MAX_ROWS:
                raise InvalidCSV("TOO_MANY_ROWS", f"Select a CSV with at most {MAX_ROWS:,} data rows.")
            supplied = dict(zip(headers, raw))
            values = {field: supplied.get(field, "").strip() for field in CSV_COLUMNS}
            for field in ("platform", "currency", *CONTEXT_FIELDS):
                values[field] = values[field].upper()
            rows.append(validate_row(number, values, len(raw) > len(headers)))
    except csv.Error as error:
        raise InvalidCSV("MALFORMED_CSV", f"Malformed CSV near line {reader.line_num}: {error}.") from error
    if not rows:
        raise InvalidCSV("EMPTY_FILE", "The CSV contains no data rows.")
    return rows
