"""Environment-backed settings.

All secrets come from the environment or a local `.env` file. Nothing in this
module writes secrets to disk, logs them, or exposes them in reports.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LCES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    provider: str = "mock"
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=3, ge=1, le=8)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    # Research emits a structured record per window; a larger ceiling mostly
    # buys generation time (and timeout risk) without more useful content.
    research_max_output_tokens: int = Field(default=4096, ge=256, le=65536)

    # Accept both LCES_-prefixed and conventional vendor variable names.
    deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LCES_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", "LCES_API_KEY"),
    )
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LCES_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_version: str = "2023-06-01"

    # llama.cpp llama-server / Ollama / LM Studio expose an OpenAI-compatible API.
    # `local_model` empty means "discover from /v1/models on first use".
    local_base_url: str = "http://127.0.0.1:8080/v1"
    local_model: str = ""
    local_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LCES_LOCAL_API_KEY", "LLAMA_API_KEY"),
    )
    local_json_mode: bool = True
    local_timeout_seconds: float = Field(default=300.0, gt=0)
    local_max_retries: int = Field(default=2, ge=1, le=5)
    # Keep research prompts inside a small local context window (~8K–16K tokens).
    local_prompt_char_budget: int = Field(default=24_000, ge=2000)

    # Gate 3 browser checks run only when Playwright (the `browser` extra) is
    # installed; set LCES_BROWSER_QA=false to skip them deliberately.
    browser_qa: bool = True

    projects_dir: Path = Path("projects")
    database_path: Path = Path("var/lces.sqlite3")
    # Append-only JSONL log for tool calls (CLI/MCP). Contains no secrets.
    tool_log_path: Path = Path("var/tool_calls.jsonl")
    # Optional price table for `lces usage`; absent means costs are not reported.
    pricing_file: Path | None = None
    routing_file: Path | None = None
    log_level: str = "INFO"

    max_source_bytes: int = Field(default=50_000_000, ge=1024)
    prompt_char_budget: int = Field(default=120_000, ge=4000)

    def api_key_for(self, provider: str) -> str:
        provider = provider.lower()
        if provider == "deepseek":
            return self.deepseek_api_key
        if provider == "anthropic":
            return self.anthropic_api_key
        if provider in {"local", "llama", "llama_cpp", "llamacpp"}:
            return self.local_api_key
        return ""

    def model_for(self, provider: str) -> str:
        provider = provider.lower()
        if provider == "deepseek":
            return self.deepseek_model
        if provider == "anthropic":
            return self.anthropic_model
        if provider in {"local", "llama", "llama_cpp", "llamacpp"}:
            return self.local_model or "auto (llama-server)"
        return "mock-deterministic"

    def base_url_for(self, provider: str) -> str:
        provider = provider.lower()
        if provider == "deepseek":
            return self.deepseek_base_url
        if provider == "anthropic":
            return self.anthropic_base_url
        if provider in {"local", "llama", "llama_cpp", "llamacpp"}:
            return self.local_base_url
        return ""

    def describe(self) -> str:
        """Human-readable summary that never includes key material."""

        return (
            f"provider={self.provider} model={self.model_for(self.provider)} "
            f"projects_dir={self.projects_dir} database={self.database_path}"
        )


def get_settings() -> Settings:
    return Settings()
