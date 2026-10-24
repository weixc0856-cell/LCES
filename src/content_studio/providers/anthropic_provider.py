"""Anthropic Messages API adapter."""

from __future__ import annotations

import time
from typing import Any

import httpx

from content_studio.errors import ConfigurationError, ProviderResponseError
from content_studio.providers.base import (
    GenerationRequest,
    GenerationResult,
    Message,
    ModelProvider,
    Usage,
    elapsed_ms,
)
from content_studio.providers.http import post_json


def _merge_consecutive(messages: list[Message]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for message in messages:
        if message.role == "system":
            continue
        if merged and merged[-1]["role"] == message.role:
            merged[-1]["content"] += "\n\n" + message.content
        else:
            merged.append({"role": message.role, "content": message.content})
    return merged


class AnthropicProvider(ModelProvider):
    name = "anthropic"
    native_json_mode = False  # The Messages API has no response_format field.

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://api.anthropic.com",
        version: str = "2023-06-01",
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "missing API key for provider 'anthropic'; set LCES_ANTHROPIC_API_KEY"
            )
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.max_retries = max_retries
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "LCES/0.2 (+local)"},
        )

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": self.version,
            "Content-Type": "application/json",
        }

    def generate(self, request: GenerationRequest) -> GenerationResult:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": _merge_consecutive(request.messages),
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

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

        blocks = data.get("content") or []
        text_parts = [
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(part for part in text_parts if part).strip()
        if not text:
            raise ProviderResponseError(
                f"anthropic returned no text content (stop_reason={data.get('stop_reason')})",
                provider=self.name,
            )

        usage_data = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_data.get("input_tokens") or 0),
            output_tokens=int(usage_data.get("output_tokens") or 0),
        )
        return GenerationResult(
            text=text,
            provider=self.name,
            model=str(data.get("model") or self.model),
            usage=usage,
            latency_ms=latency,
            finish_reason=str(data.get("stop_reason") or ""),
            request_id=str(data.get("id") or ""),
        )

    def close(self) -> None:
        self._client.close()
