from dataclasses import asdict, dataclass
import re

from pydantic import ValidationError

STATUSES = {"completed", "failed", "incomplete", "in_progress", "queued", "cancelled"}


@dataclass(frozen=True)
class Diagnostic:
    category: str
    rule: str
    field_path: str
    expected: str
    actual: str | int | dict | None = None


class OutputRejection(ValueError):
    def __init__(self, category: str, rule: str, path: str, expected: str, actual=None):
        super().__init__(rule)
        self.diagnostic = Diagnostic(category, rule, path, expected, actual)


def schema_rejection(error: ValidationError, fields: set[str]) -> OutputRejection:
    def pointer(parts):
        safe = [str(value) if isinstance(value, int) and 0 <= value <= 2800
                or isinstance(value, str) and value in fields else "<redacted>" for value in parts[:6]]
        return "/" + "/".join(safe)

    errors = error.errors(include_input=False, include_context=False, include_url=False)[:5]
    items = [{"field_path": pointer(item["loc"]), "type": item["type"]} for item in errors]
    return OutputRejection("SCHEMA", "RESPONSE_SCHEMA", items[0]["field_path"] if items else "/",
                           "The versioned response shape, field types and required keys.", {"errors": items})


def safe_status(value: str | None) -> str:
    return value if value in STATUSES else "unavailable"


def diagnostic_artifact(item: Diagnostic, *, status: str | None, schema_version: str,
                        evidence_fingerprint: str, attempt_id: int) -> dict:
    return {
        "artifact_version": 1,
        **asdict(item),
        "provider_response_status": safe_status(status),
        "schema_version": schema_version,
        "evidence_fingerprint": evidence_fingerprint,
        "analysis_attempt_id": attempt_id,
    }


NUMBER = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?")
