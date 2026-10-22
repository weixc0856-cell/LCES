"""Provider factory."""

from __future__ import annotations

from content_studio.errors import ConfigurationError
from content_studio.providers.anthropic_provider import AnthropicProvider
from content_studio.providers.base import ModelProvider
from content_studio.providers.local_llama_cpp import LocalLlamaProvider
from content_studio.providers.mock import MockProvider
from content_studio.providers.openai_compatible import DeepSeekProvider
from content_studio.settings import Settings

LOCAL_NAMES = {"local", "llama", "llama_cpp", "llamacpp", "llama-server"}
KNOWN_PROVIDERS = {"mock", "deepseek", "anthropic", *LOCAL_NAMES}


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
    if name in LOCAL_NAMES:
        return LocalLlamaProvider(
            base_url=settings.local_base_url,
            model=settings.local_model,
            api_key=settings.local_api_key,
            timeout=settings.local_timeout_seconds,
            max_retries=settings.local_max_retries,
            json_mode=settings.local_json_mode,
        )
    raise ConfigurationError(
        f"unknown provider '{name}'; expected one of {sorted(KNOWN_PROVIDERS)}"
    )
