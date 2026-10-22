"""Environment-backed settings.

All secrets come from the environment or a local `.env` file. Nothing in this
module writes secrets to disk, logs them, or exposes them in reports.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LCES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "mock"
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=3, ge=1, le=8)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, ge=256, le=65536)

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_version: str = "2023-06-01"

    projects_dir: Path = Path("projects")
    database_path: Path = Path("var/lces.sqlite3")
    log_level: str = "INFO"

    max_source_bytes: int = Field(default=50_000_000, ge=1024)
    prompt_char_budget: int = Field(default=120_000, ge=4000)

    def api_key_for(self, provider: str) -> str:
        provider = provider.lower()
        if provider == "deepseek":
            return self.deepseek_api_key
        if provider == "anthropic":
            return self.anthropic_api_key
        return ""

    def model_for(self, provider: str) -> str:
        provider = provider.lower()
        if provider == "deepseek":
            return self.deepseek_model
        if provider == "anthropic":
            return self.anthropic_model
        return "mock-deterministic"

    def base_url_for(self, provider: str) -> str:
        provider = provider.lower()
        if provider == "deepseek":
            return self.deepseek_base_url
        if provider == "anthropic":
            return self.anthropic_base_url
        return ""

    def describe(self) -> str:
        """Human-readable summary that never includes key material."""

        return (
            f"provider={self.provider} model={self.model_for(self.provider)} "
            f"projects_dir={self.projects_dir} database={self.database_path}"
        )


def get_settings() -> Settings:
    return Settings()
