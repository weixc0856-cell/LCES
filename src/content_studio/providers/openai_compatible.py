"""OpenAI-compatible chat completions adapter (used for DeepSeek)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from content_studio.errors import ConfigurationError, ProviderResponseError
from content_studio.providers.base import (
    GenerationRequest,
    GenerationResult,
    ModelProvider,
    Usage,
    elapsed_ms,
)
from content_studio.providers.http import post_json


class OpenAICompatibleProvider(ModelProvider):
    name = "openai_compatible"
    native_json_mode = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise ConfigurationError(f"missing API key for provider '{self.name}'; set it in .env")
        if not base_url:
            raise ConfigurationError(f"missing base_url for provider '{self.name}'")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "LCES/0.2 (+local)"},
        )

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, request: GenerationRequest) -> GenerationResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.json_mode and self.native_json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        data = post_json(
            self._client,
            self.endpoint,
            payload,
            self._headers(),
            provider=self.name,
            max_retries=self.max_retries,
        )
        latency = elapsed_ms(started)

        choices = data.get("choices") or []
        if not choices:
            raise ProviderResponseError(f"{self.name} response has no choices", provider=self.name)
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        if not isinstance(text, str) or not text.strip():
            raise ProviderResponseError(f"{self.name} returned empty content", provider=self.name)

        usage_data = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_data.get("prompt_tokens") or 0),
            output_tokens=int(usage_data.get("completion_tokens") or 0),
        )
        return GenerationResult(
            text=text,
            provider=self.name,
            model=str(data.get("model") or self.model),
            usage=usage,
            latency_ms=latency,
        )

    def close(self) -> None:
        self._client.close()


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
