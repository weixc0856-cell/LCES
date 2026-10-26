"""Shared exception types.

Every failure is classified so callers can decide whether to retry, fail the
stage, or fail the release gate. Nothing here ever carries secret values.

Failure codes are loaded from ``config/error_codes.json`` so the Python
adapter and the Motion Canvas driver share one table. Each code fixes the
terminal state, the process exit code, and the stage it belongs to; a build
may reach exactly one terminal state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ERROR_CODES_PATH = Path(__file__).resolve().parents[2] / "config" / "error_codes.json"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    stage: str
    terminal: str
    exit_code: int
    retryable: bool
    description: str = ""


def _load_error_codes() -> dict[str, ErrorCode]:
    try:
        payload = json.loads(ERROR_CODES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - packaging failure
        raise RuntimeError(f"cannot load {ERROR_CODES_PATH}: {exc}") from exc
    codes: dict[str, ErrorCode] = {}
    for name, spec in payload.get("codes", {}).items():
        codes[name] = ErrorCode(
            code=name,
            stage=str(spec["stage"]),
            terminal=str(spec["terminal"]),
            exit_code=int(spec["exit_code"]),
            retryable=bool(spec.get("retryable", False)),
            description=str(spec.get("description", "")),
        )
    if not codes:
        raise RuntimeError(f"no error codes defined in {ERROR_CODES_PATH}")
    return codes


ERROR_CODES = _load_error_codes()


def error_code_names() -> frozenset[str]:
    return frozenset(ERROR_CODES)


def exit_code_for(code: str) -> int:
    return ERROR_CODES[code].exit_code


def terminal_for(code: str) -> str:
    return ERROR_CODES[code].terminal


def stage_for(code: str) -> str:
    return ERROR_CODES[code].stage


class LCESError(Exception):
    """Base class for expected LCES failures."""

    code: str = ""


class ConfigurationError(LCESError):
    """The local environment or project configuration is not usable."""


class IngestionError(LCESError):
    """A source could not be fetched, parsed, or stored."""


class ValidationFailure(LCESError):
    """Structured model output or project data failed validation."""


class ProviderError(LCESError):
    """A model provider call failed.

    ``retryable`` is advisory: the provider already retried where it could.
    """

    def __init__(self, message: str, *, retryable: bool = False, provider: str = "") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


class ProviderResponseError(ProviderError):
    """The provider responded, but not with usable content."""


class OutputTruncatedError(ProviderResponseError):
    """The provider stopped at the output budget, so the content is partial.

    Retrying the identical request will truncate again: the caller must raise
    the budget or split the work. ``retryable`` stays true only for routing
    purposes (another provider with a larger budget may succeed).
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        finish_reason: str = "",
    ) -> None:
        super().__init__(message, retryable=True, provider=provider)
        self.model = model
        self.finish_reason = finish_reason


class RenderError(LCESError):
    """A renderer failed, or its output failed the renderer's own checks."""

    def __init__(self, message: str, *, code: str = "render_failed", stage: str = "") -> None:
        super().__init__(message)
        if code not in ERROR_CODES:
            raise ValueError(f"unknown LCES error code '{code}'")
        self.code = code
        self.stage = stage or ERROR_CODES[code].stage

    @property
    def terminal(self) -> str:
        return ERROR_CODES[self.code].terminal

    @property
    def exit_code(self) -> int:
        return ERROR_CODES[self.code].exit_code


class RenderCancelled(RenderError):
    """The build was cancelled; partial output must not be published."""

    def __init__(self, message: str = "render cancelled", *, stage: str = "") -> None:
        super().__init__(message, code="cancelled", stage=stage)


class UnsupportedVisualType(LCESError):
    """No renderer is registered for the requested visual type."""


class MediaError(LCESError):
    """A media file could not be probed, decoded, or extracted."""


class ToolPermissionError(LCESError):
    """A tool call exceeds the caller's access level."""


def classify_error(exc: BaseException) -> str:
    """A bounded class name for run records (SAD-001 §8.3).

    This is deliberately coarser than the exception message: the class decides
    whether a later step may retry, and the message carries the detail. Unknown
    exceptions fall back to the class name, never to an empty value.
    """

    if isinstance(exc, RenderError):
        return exc.code
    if isinstance(exc, OutputTruncatedError):
        return "output_truncated"
    if isinstance(exc, ProviderResponseError):
        return "provider_response"
    if isinstance(exc, ProviderError):
        return "provider"
    if isinstance(exc, ConfigurationError):
        return "configuration"
    if isinstance(exc, IngestionError):
        return "ingestion"
    if isinstance(exc, ValidationFailure):
        return "validation"
    if isinstance(exc, MediaError):
        return "media"
    if isinstance(exc, UnsupportedVisualType):
        return "unsupported_visual"
    if isinstance(exc, ToolPermissionError):
        return "tool_permission"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "io"
    return exc.__class__.__name__
