from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    GOOGLE_ADS = "GOOGLE_ADS"
    META_ADS = "META_ADS"


class CampaignStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class SourceType(StrEnum):
    SYNTHETIC_SEED = "SYNTHETIC_SEED"
    CSV_UPLOAD = "CSV_UPLOAD"


class ImportStatus(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    REJECTED = "REJECTED"
    NO_NEW_ROWS = "NO_NEW_ROWS"


@dataclass(frozen=True, order=True)
class ReportingContext:
    conversion_action: str
    attribution_method: str
    attribution_window: str
    date_basis: str


CANONICAL_CONTEXT = ReportingContext("PURCHASE", "LAST_CLICK", "7D_CLICK", "INTERACTION_DATE")
CONTEXT_OPTIONS = {
    "conversion_action": {"PURCHASE"},
    "attribution_method": {"LAST_CLICK", "DATA_DRIVEN", "LINEAR", "UNKNOWN"},
    "attribution_window": {"7D_CLICK", "1D_CLICK", "30D_CLICK", "7D_CLICK_1D_VIEW", "UNKNOWN"},
    "date_basis": {"INTERACTION_DATE", "CONVERSION_DATE", "UNKNOWN"},
}
CONTEXT_FIELDS = tuple(CONTEXT_OPTIONS)
