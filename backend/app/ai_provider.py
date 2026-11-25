from dataclasses import dataclass
from hashlib import sha256
import time

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI

from app.ai_config import AISettings
from app.ai_contract import AnalysisOutput, SYSTEM_INSTRUCTIONS, parse_output, provider_payload, provider_schema
from app.ai_diagnostics import Diagnostic, OutputRejection, safe_status
from app.detection import canonical_json

REQUEST_TIMEOUT = 25.0
MAX_OUTPUT_TOKENS = 2800
CHECK_TTL = 60


class ProviderFailure(Exception):
    def __init__(self, code: str, message: str, status: int, usage: dict | None = None, *,
                 diagnostic: Diagnostic | None = None, provider_status: str | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.usage = usage
        self.diagnostic = diagnostic or Diagnostic("PROVIDER", code, "/", "An available provider and a response.")
        self.provider_status = safe_status(provider_status)


@dataclass(frozen=True)
class ProviderResult:
    output: AnalysisOutput | dict
    usage: dict | None
    provider_status: str = "completed"


@dataclass(frozen=True)
class StructuredResponse:
    text: str
    usage: dict | None
    status: str


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
        result = self.structured(settings, payload=provider_payload(snapshot), schema=provider_schema(snapshot),
                                 instructions=SYSTEM_INSTRUCTIONS, name="CampaignAnalysis",
                                 max_output_tokens=MAX_OUTPUT_TOKENS)
        try:
            output = parse_output(result.text)
        except OutputRejection as error:
            raise ProviderFailure("AI_INVALID_OUTPUT", "The AI response did not match the required structure.", 502,
                                  result.usage, diagnostic=error.diagnostic, provider_status=result.status) from None
        return ProviderResult(output, result.usage, result.status)

    def structured(self, settings: AISettings, *, payload: dict, schema: dict, instructions: str,
                   name: str, max_output_tokens: int) -> StructuredResponse:
        model = settings.selected_model
        options = {"reasoning": {"effort": "low"}} if model == "gpt-6-luna" or model.startswith("gpt-6-luna-") else {}
        with self._client(settings, REQUEST_TIMEOUT) as client:
            for attempt in range(settings.ai_provider_max_attempts):
                try:
                    response = client.responses.create(
                        model=model,
                        instructions=instructions,
                        input=[{"role": "user", "content": canonical_json(payload)}],
                        text={"format": {"type": "json_schema", "name": name, "strict": True,
                                         "schema": schema}},
                        max_output_tokens=max_output_tokens,
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
                    reason = getattr(response.incomplete_details, "reason", None)
                    rule = "RESPONSE_INCOMPLETE" if response.status != "completed" else "RESPONSE_NO_TEXT"
                    diagnostic = Diagnostic("RESPONSE", rule, "/status", "A completed response containing structured text.", {
                        "reason": reason if reason in {"max_output_tokens", "content_filter"} else "unavailable",
                        "text_present": bool(response.output_text),
                    })
                    raise ProviderFailure("AI_INVALID_OUTPUT", "OpenAI did not return a complete analysis.", 502, usage,
                                          diagnostic=diagnostic, provider_status=response.status)
                return StructuredResponse(response.output_text, usage, response.status)
        raise AssertionError("The bounded provider loop did not resolve.")


_provider = OpenAIProvider()


def get_ai_provider() -> OpenAIProvider:
    return _provider
