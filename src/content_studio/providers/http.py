"""HTTP helper with bounded retries and secret-safe error messages."""

from __future__ import annotations

import time
from typing import Any

import httpx

from content_studio.errors import ProviderError, ProviderResponseError

RETRYABLE_STATUS = {408, 409, 425, 429}


def post_json(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    provider: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    delay = 1.0
    last_error = "unknown error"
    for attempt in range(1, max_retries + 1):
        try:
            response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            last_error = "request timed out"
            if attempt == max_retries:
                raise ProviderError(
                    f"{provider} request timed out after {max_retries} attempts",
                    retryable=True,
                    provider=provider,
                ) from exc
        except httpx.HTTPError as exc:
            last_error = f"transport error ({exc.__class__.__name__})"
            if attempt == max_retries:
                raise ProviderError(
                    f"{provider} transport error after {max_retries} attempts: {last_error}",
                    retryable=True,
                    provider=provider,
                ) from exc
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ProviderResponseError(
                        f"{provider} returned a non-JSON response", provider=provider
                    ) from exc
                if not isinstance(data, dict):
                    raise ProviderResponseError(
                        f"{provider} returned an unexpected JSON shape", provider=provider
                    )
                return data

            last_error = f"HTTP {response.status_code}: {response.text[:400]}"
            retryable = response.status_code in RETRYABLE_STATUS or response.status_code >= 500
            if not retryable or attempt == max_retries:
                raise ProviderError(
                    f"{provider} API error ({last_error})", retryable=retryable, provider=provider
                )
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise ProviderError(f"{provider} API failed: {last_error}", retryable=True, provider=provider)
