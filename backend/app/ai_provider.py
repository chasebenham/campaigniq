from dataclasses import dataclass
from hashlib import sha256
import time

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI

from app.ai_config import AISettings
from app.ai_contract import (
    AnalysisOutput, SYSTEM_INSTRUCTIONS, coverage_references, provider_schema, references, required_references,
)
from app.detection import canonical_json

REQUEST_TIMEOUT = 25.0
MAX_OUTPUT_TOKENS = 2800
CHECK_TTL = 60


class ProviderFailure(Exception):
    def __init__(self, code: str, message: str, status: int, usage: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.usage = usage


@dataclass(frozen=True)
class ProviderResult:
    output: AnalysisOutput | dict
    usage: dict | None


@dataclass(frozen=True)
class ProviderCheck:
    ok: bool
    code: str | None = None
    message: str | None = None


def classify_provider_error(error: APIError) -> tuple[ProviderFailure, bool]:
    status = error.status_code if isinstance(error, APIStatusError) else None
    if isinstance(error, APITimeoutError) or status == 408:
        return ProviderFailure("AI_PROVIDER_TIMEOUT", "OpenAI timed out. Try again.", 504), True
    if getattr(error, "code", None) == "insufficient_quota":
        return ProviderFailure("AI_PROVIDER_QUOTA", "OpenAI reported insufficient quota. Check project billing and limits.", 503), False
    if status == 401:
        return ProviderFailure("AI_PROVIDER_AUTH", "OpenAI rejected the configured API key.", 502), False
    if status == 403:
        return ProviderFailure("AI_PROVIDER_PERMISSION", "OpenAI denied this operation. Check project and key permissions.", 502), False
    if status == 404 or getattr(error, "code", None) == "model_not_found":
        return ProviderFailure("AI_PROVIDER_MODEL_UNAVAILABLE", "The configured model is unavailable to this OpenAI project.", 502), False
    if isinstance(error, APIConnectionError) or status == 429 or (status is not None and status >= 500):
        return ProviderFailure("AI_PROVIDER_UNAVAILABLE", "OpenAI is temporarily unavailable or rate limited. Try again shortly.", 503), True
    return ProviderFailure("AI_PROVIDER_ERROR", "OpenAI rejected the request. Check the configured model and its Structured Outputs support.", 502), False


class OpenAIProvider:
    def __init__(self):
        self._last_check: tuple[str, float, ProviderCheck] | None = None

    def _client(self, settings: AISettings, timeout: float):
        return OpenAI(api_key=settings.openai_api_key.get_secret_value().strip(), base_url="https://api.openai.com/v1",
                      timeout=timeout, max_retries=0)

    def _key(self, settings: AISettings) -> str:
        return sha256(f"{settings.selected_model}\0{settings.openai_api_key.get_secret_value().strip()}".encode()).hexdigest()

    def _remember(self, settings: AISettings, result: ProviderCheck) -> ProviderCheck:
        self._last_check = (self._key(settings), time.monotonic() + CHECK_TTL, result)
        return result

    def cached_status(self, settings: AISettings) -> ProviderCheck | None:
        prior = self._last_check
        if prior and prior[1] > time.monotonic() and prior[0] == self._key(settings):
            return prior[2]
        return None

    def check(self, settings: AISettings) -> ProviderCheck:
        if prior := self.cached_status(settings):
            return prior
        try:
            with self._client(settings, 8) as client:
                client.models.retrieve(settings.selected_model)
        except APIError as error:
            failure, _ = classify_provider_error(error)
            return self._remember(settings, ProviderCheck(False, failure.code, str(failure)))
        return self._remember(settings, ProviderCheck(True))

    def generate(self, settings: AISettings, snapshot: dict) -> ProviderResult:
        payload = {
            "finding_id": snapshot["finding_id"], "evidence": snapshot["evidence"],
            "allowed_evidence_references": list(references(snapshot)),
            "required_evidence_references": required_references(snapshot),
        }
        if snapshot["evidence"].get("rule", {}).get("category") == "DATA_QUALITY":
            payload["coverage_evidence"] = coverage_references(snapshot)
        schema = provider_schema(snapshot)
        model = settings.selected_model
        options = {"reasoning": {"effort": "low"}} if model == "gpt-6-luna" or model.startswith("gpt-6-luna-") else {}
        with self._client(settings, REQUEST_TIMEOUT) as client:
            for attempt in range(settings.ai_provider_max_attempts):
                try:
                    response = client.responses.create(
                        model=model,
                        instructions=SYSTEM_INSTRUCTIONS,
                        input=[{"role": "user", "content": canonical_json(payload)}],
                        text={"format": {"type": "json_schema", "name": "CampaignAnalysis", "strict": True,
                                         "schema": schema}},
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        store=False,
                        **options,
                    )
                except APIError as error:
                    failure, transient = classify_provider_error(error)
                    if transient and attempt + 1 < settings.ai_provider_max_attempts:
                        time.sleep(0.25)
                        continue
                    self._remember(settings, ProviderCheck(False, failure.code, str(failure)))
                    raise failure from error
                self._remember(settings, ProviderCheck(True))
                usage = response.usage.model_dump(mode="json") if response.usage else None
                if usage is not None:
                    usage.update(model=response.model, service_tier=response.service_tier, attempts=attempt + 1)
                if response.status != "completed" or not response.output_text:
                    raise ProviderFailure("AI_INVALID_OUTPUT", "OpenAI returned an incomplete structured result. You can retry.", 502, usage)
                try:
                    output = AnalysisOutput.model_validate_json(response.output_text)
                except ValueError as error:
                    raise ProviderFailure("AI_INVALID_OUTPUT", "OpenAI returned an unreadable structured result. You can retry.", 502, usage) from error
                return ProviderResult(output, usage)
        raise AssertionError("The bounded provider loop did not resolve.")


_provider = OpenAIProvider()


def get_ai_provider() -> OpenAIProvider:
    return _provider
