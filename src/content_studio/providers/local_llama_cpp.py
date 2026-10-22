"""Local llama.cpp (`llama-server`) adapter.

`llama-server` exposes an OpenAI-compatible API (default
``http://127.0.0.1:8080/v1``) and supports JSON-constrained output in recent
builds. The model ID is discovered from ``/v1/models`` unless configured.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from content_studio.providers.openai_compatible import OpenAICompatibleProvider


class LocalLlamaProvider(OpenAICompatibleProvider):
    name = "local"
    native_json_mode = True

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080/v1",
        model: str = "",
        api_key: str = "",
        timeout: float = 300.0,
        max_retries: int = 2,
        json_mode: bool = True,
        discover_model: bool = True,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model or "local-model",
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            require_api_key=False,
            native_json_mode=json_mode,
        )
        if not model and discover_model:
            self.model = self.discover_model()

    @property
    def root_url(self) -> str:
        return self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    def list_models(self, timeout: float = 5.0) -> list[str]:
        try:
            response = self._client.get(f"{self.base_url}/models", timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return []
        return [
            str(entry.get("id")) for entry in entries if isinstance(entry, dict) and entry.get("id")
        ]

    def discover_model(self) -> str:
        models = self.list_models()
        return models[0] if models else "local-model"

    def probe(self) -> dict[str, Any]:
        """Diagnostics for `lces models`; never calls a completion endpoint."""

        started = time.perf_counter()
        result: dict[str, Any] = {
            "base_url": self.base_url,
            "root_url": self.root_url,
            "reachable": False,
            "health": None,
            "models": [],
            "latency_ms": 0,
            "error": "",
        }
        try:
            response = self._client.get(f"{self.root_url}/health", timeout=5.0)
            result["health"] = response.json() if response.content else response.status_code
            result["reachable"] = response.status_code < 500
        except (httpx.HTTPError, ValueError) as exc:
            result["error"] = f"{exc.__class__.__name__}: {exc}"
        result["models"] = self.list_models()
        result["reachable"] = result["reachable"] or bool(result["models"])
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return result
