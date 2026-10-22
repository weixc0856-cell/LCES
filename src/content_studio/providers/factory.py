"""Provider factory."""

from __future__ import annotations

from content_studio.errors import ConfigurationError
from content_studio.providers.anthropic_provider import AnthropicProvider
from content_studio.providers.base import ModelProvider
from content_studio.providers.mock import MockProvider
from content_studio.providers.openai_compatible import DeepSeekProvider
from content_studio.settings import Settings


def build_provider(settings: Settings, override: str | None = None) -> ModelProvider:
    name = (override or settings.provider or "mock").strip().lower()
    if name == "mock":
        return MockProvider()
    if name == "deepseek":
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        )
    if name == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            version=settings.anthropic_version,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        )
    raise ConfigurationError(f"unknown provider '{name}'; expected mock, deepseek, or anthropic")
