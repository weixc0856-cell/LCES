"""Shared exception types.

Every failure is classified so callers can decide whether to retry, fail the
stage, or fail the release gate. Nothing here ever carries secret values.
"""

from __future__ import annotations


class LCESError(Exception):
    """Base class for expected LCES failures."""


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


class RenderError(LCESError):
    """A renderer failed, or its output failed the renderer's own checks."""


class UnsupportedVisualType(LCESError):
    """No renderer is registered for the requested visual type."""


class MediaError(LCESError):
    """A media file could not be probed, decoded, or extracted."""
