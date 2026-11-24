from pydantic import Field, SecretStr, field_validator

from app.config import Settings

DEFAULT_MODEL = "gpt-6-luna"


class AISettings(Settings):
    ai_analysis_enabled: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str | None = Field(None, max_length=120)
    ai_request_limit_per_hour: int = Field(8, ge=1, le=100)
    ai_provider_max_attempts: int = Field(2, ge=1, le=2)

    @field_validator("openai_model", mode="before")
    @classmethod
    def normalize_model(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @property
    def selected_model(self) -> str:
        return self.openai_model or DEFAULT_MODEL

    def unavailable_reason(self) -> str | None:
        if not self.ai_analysis_enabled:
            return "DISABLED"
        if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
            return "MISSING_API_KEY"
        return None


def get_ai_settings() -> AISettings:
    return AISettings()
