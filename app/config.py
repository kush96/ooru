"""Application settings. Field names match .env names, ignoring case."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # The same .env also contains Docker settings.
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )

    # Groq by default; use LLM_API_KEY for another OpenAI-compatible server.
    groq_api_key: SecretStr = SecretStr("")
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: HttpUrl = HttpUrl("https://api.groq.com/openai/v1")
    llm_model: str = Field(default="openai/gpt-oss-120b", min_length=1)
    llm_json_mode: Literal["json_schema", "json_object"] = "json_schema"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    llm_max_tokens: int = Field(default=2048, gt=0)

    # Chat does not need a database; import/map scripts do.
    database_url: SecretStr = SecretStr("")

    @property
    def is_groq(self) -> bool:
        return self.llm_base_url.host == "api.groq.com"

    @model_validator(mode="after")
    def check_model(self):
        # A different server must name its own model, not inherit Groq's default.
        if not self.is_groq and "llm_model" not in self.model_fields_set:
            raise ValueError("Set LLM_MODEL explicitly for your model server.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Load once per process. Restart the app after editing .env."""
    return Settings()
