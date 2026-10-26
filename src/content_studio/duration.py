"""Deterministic per-unit duration budgets.

The course target is a product requirement; it is not distributed evenly across
units. Each unit gets a weight from its teaching load (objectives, concepts,
formulas, visual blocks, claims, checks), the weights are water-filled into the
contract target with per-unit floors/ceilings, and the result is compared with
the current narration estimate and, when its script hash is current, the TTS
measurement.

Estimated and measured seconds are separate fields and are never folded
together. A stale TTS record is reported as invalid, not as a measurement of the
current script.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from content_studio.content import NARRATION_CHARS_PER_SECOND
from content_studio.course_quality import load_contract, load_timing
from content_studio.models import (
    CourseMaster,
    LearningUnit,
    PublicContent,
    SpeakerScript,
)
from content_studio.units import delivered_units
from content_studio.utils import sha256_file, write_json

BUDGET_PATH = Path("internal") / "qa" / "duration_budget.json"
MIN_UNIT_SECONDS = 45
MAX_UNIT_SECONDS = 480
VISUAL_BLOCKS = {"svg", "table", "interactive", "figure", "chart", "diagram", "graph"}


@dataclass(frozen=True)
class UnitBudget:
    unit_id: str
    scene_id: str
    title: str
    weight: float
    components: dict[str, float]
    budget_seconds: int
    estimated_seconds: int
    measured_seconds: float | None
    gap_seconds: int
    basis: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "scene_id": self.scene_id,
            "title": self.title,
            "weight": round(self.weight, 2),
            "components": {key: round(value, 2) for key, value in self.components.items()},
            "budget_seconds": self.budget_seconds,
            "estimated_seconds": self.estimated_seconds,
            "measured_seconds": self.measured_seconds,
            "gap_seconds": self.gap_seconds,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class DurationBudget:
    project_id: str
    target_minutes: float
    lower_seconds: float
    upper_seconds: float
    total_budget_seconds: int
    total_estimated_seconds: int
    total_measured_seconds: float | None
    measured_valid: bool
    units: tuple[UnitBudget, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "project_id": self.project_id,
            "target_minutes": self.target_minutes,
            "allowed_seconds": {
                "min": round(self.lower_seconds, 2),
                "max": round(self.upper_seconds, 2),
            },
            "totals": {
                "budget_seconds": self.total_budget_seconds,
                "estimated_seconds": self.total_estimated_seconds,
                "measured_seconds": self.total_measured_seconds,
                "measured_valid": self.measured_valid,
                "gap_seconds": max(0, self.total_budget_seconds - self.total_estimated_seconds),
            },
            "units": [unit.as_dict() for unit in self.units],
        }


def _weight(unit: LearningUnit, slide_blocks: Sequence[str]) -> tuple[float, dict[str, float]]:
    components = {
        "base": 1.0,
        "objectives": 1.2 * len(unit.objectives),
        "concepts": 0.8 * len(unit.key_concepts),
        "formulas": 1.0 * sum(1 for kind in slide_blocks if kind == "formula"),
        "visuals": 0.8 * sum(1 for kind in slide_blocks if kind in VISUAL_BLOCKS),
        "claims": 0.5 * min(6, len(unit.claim_ids)),
        "checks": 0.4 * sum(1 for kind in slide_blocks if kind == "check"),
        "requirements": 0.3 * len(unit.visual_requirements),
    }
    return round(sum(components.values()), 3), components


def _allocate(weights: dict[str, float], target_seconds: int) -> dict[str, int]:
    """Water-fill weights into the target with per-unit floors and ceilings."""

    remaining = float(target_seconds)
    active = set(weights)
    budgets: dict[str, int] = {}
    while active:
        total_weight = sum(weights[unit] for unit in active) or 1.0
        clamped = False
        for unit in sorted(active):
            value = remaining * weights[unit] / total_weight
            if value <= MIN_UNIT_SECONDS:
                budgets[unit] = MIN_UNIT_SECONDS
                remaining -= MIN_UNIT_SECONDS
                active.remove(unit)
                clamped = True
            elif value >= MAX_UNIT_SECONDS:
                budgets[unit] = MAX_UNIT_SECONDS
                remaining -= MAX_UNIT_SECONDS
                active.remove(unit)
                clamped = True
        if clamped:
            continue
        total_weight = sum(weights[unit] for unit in active) or 1.0
        for unit in active:
            budgets[unit] = int(round(remaining * weights[unit] / total_weight))
        break
    # Rounding (or an early clamp) can leave a gap; fill it without exceeding
    # the per-unit ceiling.
    diff = target_seconds - sum(budgets.values())
    while diff > 0:
        open_units = [unit for unit in budgets if budgets[unit] < MAX_UNIT_SECONDS]
        if not open_units:
            break
        weight_sum = sum(weights[unit] for unit in open_units) or 1.0
        added = 0
        for unit in open_units:
            if diff <= 0:
                break
            share = max(1, int(round(diff * weights[unit] / weight_sum)))
            add = min(share, MAX_UNIT_SECONDS - budgets[unit], diff)
            budgets[unit] += add
            diff -= add
            added += add
        if added == 0:
            break
    return budgets


def build_duration_budget(
    project_dir: Path,
    master: CourseMaster,
    content: PublicContent,
    script: SpeakerScript | None,
) -> DurationBudget:
    contract = load_contract(project_dir)
    target_minutes = contract.target_duration_minutes if contract is not None else 20.0
    target_seconds = int(round(target_minutes * 60))
    slides = {slide.slide_id: slide for slide in content.slides}
    sections = {section.slide_id: section for section in (script.sections if script else [])}
    weights: dict[str, float] = {}
    components_by_unit: dict[str, dict[str, float]] = {}
    slide_by_unit: dict[str, str] = {}
    for unit in delivered_units(master):
        scene_id = unit.scene_ids[0]
        slide = slides.get(scene_id)
        kinds = [block.type for block in slide.body] if slide is not None else []
        weight, components = _weight(unit, kinds)
        weights[unit.unit_id] = weight
        components_by_unit[unit.unit_id] = components
        slide_by_unit[unit.unit_id] = scene_id
    budgets = _allocate(weights, target_seconds)

    timing = load_timing(project_dir)
    script_path = project_dir / "internal" / "speaker_script.json"
    measured_valid = bool(
        timing is not None
        and timing.script_sha256
        and script_path.is_file()
        and timing.script_sha256 == sha256_file(script_path)
    )
    units: list[UnitBudget] = []
    for unit in delivered_units(master):
        scene_id = slide_by_unit[unit.unit_id]
        section = sections.get(scene_id)
        estimated = section.estimated_seconds if section is not None else 0
        measured = (
            timing.scene_seconds.get(scene_id)
            if measured_valid and timing is not None and scene_id in timing.scene_seconds
            else None
        )
        comparison = measured if measured is not None else float(estimated)
        budget = budgets[unit.unit_id]
        components = components_by_unit[unit.unit_id]
        basis = "权重 " + " + ".join(
            f"{name} {value:g}" for name, value in components.items() if value
        )
        units.append(
            UnitBudget(
                unit_id=unit.unit_id,
                scene_id=scene_id,
                title=unit.title,
                weight=weights[unit.unit_id],
                components=components,
                budget_seconds=budget,
                estimated_seconds=estimated,
                measured_seconds=round(measured, 2) if measured is not None else None,
                gap_seconds=max(0, int(round(budget - comparison))),
                basis=basis,
            )
        )
    total_estimated = sum(unit.estimated_seconds for unit in units)
    measured_values = [unit.measured_seconds for unit in units if unit.measured_seconds is not None]
    total_measured = (
        round(sum(measured_values), 2)
        if measured_valid and len(measured_values) == len(units)
        else None
    )
    return DurationBudget(
        project_id=content.project_id,
        target_minutes=target_minutes,
        lower_seconds=target_minutes * 60 * 0.8,
        upper_seconds=target_minutes * 60 * 1.3,
        total_budget_seconds=sum(unit.budget_seconds for unit in units),
        total_estimated_seconds=total_estimated,
        total_measured_seconds=total_measured,
        measured_valid=measured_valid,
        units=tuple(units),
    )


def write_duration_budget(project_dir: Path, budget: DurationBudget) -> Path:
    path = project_dir / BUDGET_PATH
    write_json(path, budget.as_dict())
    return path


def load_duration_budget(project_dir: Path) -> DurationBudget | None:
    path = project_dir / BUDGET_PATH
    if not path.is_file():
        return None
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    # The file is a report; callers that need live numbers rebuild it instead.
    return None if not payload.get("units") else _from_payload(payload)


def _from_payload(payload: dict[str, Any]) -> DurationBudget:
    units = tuple(
        UnitBudget(
            unit_id=item["unit_id"],
            scene_id=item["scene_id"],
            title=item["title"],
            weight=item["weight"],
            components=item["components"],
            budget_seconds=item["budget_seconds"],
            estimated_seconds=item["estimated_seconds"],
            measured_seconds=item["measured_seconds"],
            gap_seconds=item["gap_seconds"],
            basis=item["basis"],
        )
        for item in payload["units"]
    )
    totals = payload["totals"]
    return DurationBudget(
        project_id=payload["project_id"],
        target_minutes=payload["target_minutes"],
        lower_seconds=payload["allowed_seconds"]["min"],
        upper_seconds=payload["allowed_seconds"]["max"],
        total_budget_seconds=totals["budget_seconds"],
        total_estimated_seconds=totals["estimated_seconds"],
        total_measured_seconds=totals["measured_seconds"],
        measured_valid=totals["measured_valid"],
        units=units,
    )


def narration_seconds(text: str) -> float:
    """Planning estimate from characters; never a measurement."""

    return round(len(text) / NARRATION_CHARS_PER_SECOND, 2)
