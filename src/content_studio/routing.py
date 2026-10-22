"""Task-stage provider routing (PRD Phase 4, initial implementation).

Routing is opt-in: without `--routing` (or `LCES_ROUTING_FILE`) every stage uses
`LCES_PROVIDER`. Stage-level routing currently covers the three stages that
call a model; deterministic stages never route.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from content_studio.errors import ConfigurationError
from content_studio.providers.factory import KNOWN_PROVIDERS

ROUTABLE_STAGES = ("research", "outline", "generate")


class RoutingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: str = ""
    stages: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> RoutingPolicy:
        unknown_stages = sorted(set(self.stages) - set(ROUTABLE_STAGES))
        if unknown_stages:
            raise ValueError(
                f"routing stages must be a subset of {list(ROUTABLE_STAGES)}; "
                f"unknown: {unknown_stages}"
            )
        names = [self.default, *self.stages.values()]
        unknown = sorted({name for name in names if name and name.lower() not in KNOWN_PROVIDERS})
        if unknown:
            raise ValueError(f"unknown providers in routing: {unknown}")
        return self

    def provider_for(self, stage: str, fallback: str) -> str:
        return self.stages.get(stage) or self.default or fallback


def load_routing(path: Path) -> RoutingPolicy:
    if not path.is_file():
        raise ConfigurationError(f"routing file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return RoutingPolicy.model_validate(data)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise ConfigurationError(f"invalid routing file {path}: {exc}") from exc
