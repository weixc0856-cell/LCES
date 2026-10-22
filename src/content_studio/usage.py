"""Token usage and cost reporting from actual stage records (continuous work).

Numbers come from `stage_runs`, not from estimates. Costs are only reported
when a price is configured; local providers are marked as not costed rather
than claiming zero cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from content_studio.errors import ConfigurationError
from content_studio.storage import TaskStore

UNMETERED_NOTE = "未核算（本地或未计价）"
UNPRICED_NOTE = "未核算（无价格配置）"


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class PricingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = "USD"
    unmetered_providers: list[str] = Field(default_factory=lambda: ["local"])
    models: dict[str, ModelPrice] = Field(default_factory=dict)


@dataclass
class UsageRow:
    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    duration_seconds: float = 0.0
    cost: float | None = None
    cost_note: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def load_pricing(path: Path) -> PricingPolicy:
    if not path.is_file():
        raise ConfigurationError(f"pricing file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return PricingPolicy.model_validate(data)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise ConfigurationError(f"invalid pricing file {path}: {exc}") from exc


def collect_usage(store: TaskStore, project_id: str | None = None) -> list[UsageRow]:
    rows: dict[tuple[str, str], UsageRow] = {}
    for record in store.usage_rows(project_id):
        provider = str(record.get("provider") or "")
        model = str(record.get("model") or "")
        if provider in {"", "none"}:
            # Deterministic stages (ingest/build/validate) are not model calls.
            continue
        key = (provider, model)
        row = rows.setdefault(key, UsageRow(provider=provider, model=model))
        row.calls += 1
        if record.get("status") in {"fail", "failed"}:
            row.failures += 1
        usage = _parse_usage(record.get("usage_json"))
        row.input_tokens += usage.get("input_tokens", 0)
        row.output_tokens += usage.get("output_tokens", 0)
        row.duration_seconds += _duration(record.get("started_at"), record.get("finished_at"))
    return sorted(rows.values(), key=lambda item: (item.provider, item.model))


def apply_pricing(rows: list[UsageRow], policy: PricingPolicy) -> None:
    for row in rows:
        if row.provider in policy.unmetered_providers:
            row.cost, row.cost_note = None, UNMETERED_NOTE
            continue
        price = policy.models.get(row.model)
        if price is None:
            row.cost, row.cost_note = None, UNPRICED_NOTE
            continue
        row.cost = (row.input_tokens * price.input + row.output_tokens * price.output) / 1_000_000
        row.cost_note = ""


def total_cost(rows: list[UsageRow]) -> tuple[float, list[str]]:
    """Return the priced subtotal and the providers/models it excludes."""

    total = 0.0
    excluded: list[str] = []
    for row in rows:
        if row.cost is None:
            excluded.append(f"{row.provider}/{row.model}")
        else:
            total += row.cost
    return total, excluded


def _parse_usage(raw: object) -> dict[str, int]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "input_tokens": int(payload.get("input_tokens") or 0),
        "output_tokens": int(payload.get("output_tokens") or 0),
    }


def _duration(started: object, finished: object) -> float:
    if not isinstance(started, str) or not isinstance(finished, str):
        return 0.0
    try:
        start = datetime.fromisoformat(started)
        end = datetime.fromisoformat(finished)
    except ValueError:
        return 0.0
    return max(0.0, (end - start).total_seconds())
