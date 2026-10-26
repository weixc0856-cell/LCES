"""Derive playable scene contracts from the public course model.

The deck and the video pipeline must not invent two different ideas of a
"scene". This module turns every public slide into one :class:`SceneContract`
with ordered animation steps, narration and evidence references, then validates
the result before the HTML build uses it. A scene is only buildable if its
steps point at real blocks and every referenced claim/evidence row exists.

An optional ``content/scene_plan.json`` lets a course author name the steps and
choose an effect; anything it leaves out is derived deterministically. The plan
is data, so it cannot change layout or inject code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from content_studio.content import load_outline, load_speaker_script
from content_studio.errors import RenderError
from content_studio.evidence import load_claims
from content_studio.models import (
    Claim,
    ContentOutline,
    CourseMaster,
    EvidenceLedger,
    LearningUnit,
    PublicBlock,
    PublicContent,
    PublicSlide,
    SceneContract,
    SpeakerScript,
    StrictModel,
)
from content_studio.planning import load_course_master
from content_studio.research import load_evidence_ledger
from content_studio.units import materialize_course
from content_studio.utils import utc_now_iso, write_json

SceneEffect = Literal["reveal", "focus", "draw", "lab", "hold"]
DEFAULT_SCENE_MS = 60_000
MIN_STEP_MS = 800
SCENE_PLAN_PATH = Path("content") / "scene_plan.json"

SCENE_TYPES = frozenset({"concept", "structure", "process", "formula", "data", "summary"})

_EFFECT_BY_BLOCK = {
    "interactive": "lab",
    "svg": "draw",
    "formula": "focus",
    "table": "reveal",
    "check": "hold",
}
_LABEL_BY_BLOCK = {
    "paragraph": "讲解",
    "bullets": "要点",
    "formula": "公式",
    "svg": "结构图",
    "table": "数据表",
    "interactive": "实验",
    "callout": "限定",
    "check": "学习检查",
    "quote": "引文",
    "code": "代码",
    "figure": "图示",
}


class PlanStep(StrictModel):
    block: int = Field(ge=0)
    label: str = ""
    effect: SceneEffect = "reveal"
    duration_ms: int | None = Field(default=None, gt=0)


class PlanScene(StrictModel):
    unit_id: str = ""
    scene_type: str | None = None
    objective_ids: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)


class ScenePlan(StrictModel):
    schema_version: str = "1.0"
    scenes: dict[str, PlanScene] = Field(default_factory=dict)


@dataclass(frozen=True)
class SceneStep:
    step_id: str
    block_index: int
    label: str
    effect: SceneEffect
    duration_ms: int
    at_ms: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "block": self.block_index,
            "label": self.label,
            "effect": self.effect,
            "duration_ms": self.duration_ms,
            "at_ms": self.at_ms,
        }


@dataclass(frozen=True)
class DeckScene:
    contract: SceneContract
    steps: tuple[SceneStep, ...]
    objectives: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        return {
            "scene_id": self.contract.scene_id,
            "title": str(self.contract.data.get("title", "")),
            "unit_id": str(self.contract.data.get("unit_id", "")),
            "scene_type": self.contract.scene_type,
            "duration_ms": self.contract.duration_ms,
            "reset_policy": self.contract.reset_policy,
            "entry_state": self.contract.entry_state,
            "exit_state": self.contract.exit_state,
            "steps": [step.as_dict() for step in self.steps],
            "objectives": list(self.objectives),
            "claims": list(self.claims),
            "sources": list(self.contract.evidence_refs),
        }


def _error(message: str) -> RenderError:
    return RenderError(message, code="invalid_input", stage="render")


def load_scene_plan(project_dir: Path | None) -> ScenePlan | None:
    if project_dir is None:
        return None
    path = project_dir / SCENE_PLAN_PATH
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _error(f"scene plan is not valid JSON: {exc}") from exc
    try:
        return ScenePlan.model_validate(payload)
    except ValueError as exc:
        raise _error(f"scene plan is invalid: {exc}") from exc


def _scene_type(blocks: list[PublicBlock], plan: PlanScene | None) -> str:
    if plan is not None and plan.scene_type:
        if plan.scene_type not in SCENE_TYPES:
            raise _error(f"unknown scene_type '{plan.scene_type}'")
        return plan.scene_type
    kinds = {block.type for block in blocks}
    if "interactive" in kinds:
        return "data"
    if "formula" in kinds:
        return "formula"
    if kinds & {"svg", "table", "figure", "diagram", "graph"}:
        return "structure"
    return "concept"


def _default_label(block: PublicBlock, index: int) -> str:
    return _LABEL_BY_BLOCK.get(block.type, f"步骤 {index + 1}")


def _default_effect(block: PublicBlock) -> SceneEffect:
    effect = _EFFECT_BY_BLOCK.get(block.type, "reveal")
    return effect  # type: ignore[return-value]


def _section_evidence(
    outline: ContentOutline | None, ledger: EvidenceLedger | None, slide_id: str
) -> list[str]:
    if outline is None:
        return []
    section = next((item for item in outline.sections if item.slide_id == slide_id), None)
    if section is None:
        return []
    known = {record.evidence_id for record in ledger.records} if ledger is not None else None
    ids = list(section.evidence_ids)
    if known is not None:
        unknown = [item for item in ids if item not in known]
        if unknown:
            raise _error(
                f"scene {slide_id}: outline cites evidence absent from the ledger: "
                + ", ".join(unknown)
            )
    return ids


def _claim_refs(
    slide_id: str,
    evidence_ids: list[str],
    ledger: EvidenceLedger | None,
    claims: list[Claim] | None,
    plan: PlanScene | None,
) -> list[str]:
    if plan is not None and plan.claim_refs:
        refs = list(plan.claim_refs)
    elif ledger is not None:
        wanted = set(evidence_ids)
        refs = []
        for record in ledger.records:
            if record.evidence_id in wanted and record.claim_id:
                refs.append(record.claim_id)
        refs = list(dict.fromkeys(refs))
    else:
        refs = []
    if claims is not None:
        known = {claim.claim_id for claim in claims}
        unknown = [item for item in refs if item not in known]
        if unknown:
            raise _error(f"scene {slide_id}: unknown claim references: " + ", ".join(unknown))
    return refs


def _steps(
    slide_id: str,
    blocks: list[PublicBlock],
    plan: PlanScene | None,
    estimated_ms: int,
) -> tuple[SceneStep, ...]:
    if plan is not None:
        seen: set[int] = set()
        for step in plan.steps:
            if step.block >= len(blocks):
                raise _error(
                    f"scene {slide_id}: step targets block {step.block}, "
                    f"but the scene has {len(blocks)} blocks"
                )
            if step.block in seen:
                raise _error(f"scene {slide_id}: block {step.block} is animated twice")
            seen.add(step.block)
        ordered = list(plan.steps)
    else:
        ordered = []

    covered = {step.block for step in ordered}
    for index in range(len(blocks)):
        if index not in covered:
            ordered.append(PlanStep(block=index))

    per_step = max(MIN_STEP_MS, estimated_ms // max(1, len(ordered)))
    steps: list[SceneStep] = []
    cursor = 0
    for position, spec in enumerate(ordered, start=1):
        block = blocks[spec.block]
        duration = spec.duration_ms or per_step
        steps.append(
            SceneStep(
                step_id=f"s{position:02d}",
                block_index=spec.block,
                label=spec.label or _default_label(block, spec.block),
                effect=spec.effect if spec.effect != "reveal" else _default_effect(block),
                duration_ms=duration,
                at_ms=cursor,
            )
        )
        cursor += duration
    return tuple(steps)


def _outline_section(outline: ContentOutline | None, slide_id: str):
    if outline is None:
        return None
    return next((item for item in outline.sections if item.slide_id == slide_id), None)


def derive_deck_scenes(
    content: PublicContent,
    *,
    project_dir: Path | None = None,
    outline: ContentOutline | None = None,
    script: SpeakerScript | None = None,
    ledger: EvidenceLedger | None = None,
    claims: list[Claim] | None = None,
    plan: ScenePlan | None = None,
) -> tuple[DeckScene, ...]:
    """Build and validate one scene per public slide, in slide order."""

    if project_dir is not None:
        outline = outline if outline is not None else load_outline(project_dir)
        script = script if script is not None else load_speaker_script(project_dir)
        ledger = ledger if ledger is not None else load_evidence_ledger(project_dir)
        claims = claims if claims is not None else load_claims(project_dir)
        plan = plan if plan is not None else load_scene_plan(project_dir)

    if plan is not None:
        unknown_scenes = sorted(set(plan.scenes) - {slide.slide_id for slide in content.slides})
        if unknown_scenes:
            raise _error("scene plan names unknown slides: " + ", ".join(unknown_scenes))

    sections = (
        {section.slide_id: section for section in script.sections} if script is not None else {}
    )
    scenes: list[DeckScene] = []
    for slide in content.slides:
        blocks = list(slide.body)
        if not blocks:
            raise _error(f"scene {slide.slide_id}: no blocks to play")
        plan_scene = plan.scenes.get(slide.slide_id) if plan is not None else None
        section = sections.get(slide.slide_id)
        if script is not None and section is None:
            raise _error(f"scene {slide.slide_id}: speaker script has no matching section")
        estimated_ms = (
            max(1_000, section.estimated_seconds * 1_000)
            if section is not None and section.estimated_seconds
            else DEFAULT_SCENE_MS
        )
        evidence_ids = _section_evidence(outline, ledger, slide.slide_id)
        claim_refs = _claim_refs(slide.slide_id, evidence_ids, ledger, claims, plan_scene)
        steps = _steps(slide.slide_id, blocks, plan_scene, estimated_ms)
        duration_ms = sum(step.duration_ms for step in steps)
        outline_section = _outline_section(outline, slide.slide_id)
        objective_texts = list(outline_section.learning_objectives) if outline_section else []
        objectives = (
            list(plan_scene.objective_ids)
            if plan_scene is not None and plan_scene.objective_ids
            else [
                f"{slide.slide_id}-objective-{index:02d}" for index in range(len(objective_texts))
            ]
        )
        claim_texts = []
        if claims is not None:
            by_id = {claim.claim_id: claim.statement for claim in claims}
            claim_texts = [by_id[item] for item in claim_refs if item in by_id]
        required = [
            "blocks_exist",
            "steps_cover_blocks",
            "durations_positive",
            "reset_deterministic",
        ]
        if section is not None:
            required.append("narration_mapped")
        if ledger is not None:
            required.append("evidence_traceable")
        contract = SceneContract(
            scene_id=slide.slide_id,
            scene_type=_scene_type(blocks, plan_scene),
            duration_ms=duration_ms,
            narration_ref=(
                f"internal/speaker_script.json#{slide.slide_id}" if section is not None else ""
            ),
            evidence_refs=evidence_ids,
            objective_ids=objectives,
            claim_refs=claim_refs,
            entry_state={"step": 0, "revealed_blocks": 0},
            exit_state={"step": len(steps), "revealed_blocks": len(steps)},
            reset_policy="replay",
            required_checks=required,
            data={
                "title": slide.title,
                "unit_id": plan_scene.unit_id if plan_scene is not None else "",
                "objectives": objective_texts,
                "claims": claim_texts,
                "canvas": {"width": 1920, "height": 1080},
                "steps": [step.as_dict() for step in steps],
            },
        )
        scenes.append(
            DeckScene(
                contract=contract,
                steps=steps,
                objectives=tuple(objective_texts),
                claims=tuple(claim_texts),
            )
        )
    return tuple(scenes)


def scene_payload(scenes: tuple[DeckScene, ...]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "scenes": [scene.as_payload() for scene in scenes],
    }


def write_scene_contracts(project_dir: Path, scenes: tuple[DeckScene, ...]) -> Path:
    path = project_dir / "internal" / "qa" / "scene_contracts.json"
    payload = {
        "schema_version": "1.0",
        "generated_at": utc_now_iso(),
        "project_id": project_dir.name,
        "scenes": [
            {
                **scene.contract.model_dump(mode="json"),
                "steps": [step.as_dict() for step in scene.steps],
            }
            for scene in scenes
        ],
    }
    write_json(path, payload)
    return path


_SCENE_TYPE_BY_UNIT = {
    "concept": "concept",
    "formula": "formula",
    "algorithm": "process",
    "experiment": "data",
    "comparison": "structure",
    "application": "concept",
}
_STEP_WEIGHT = {
    "paragraph": 1.0,
    "bullets": 0.9,
    "formula": 1.2,
    "svg": 1.4,
    "table": 1.3,
    "interactive": 1.6,
    "callout": 0.8,
    "check": 0.7,
    "figure": 1.1,
    "chart": 1.1,
    "diagram": 1.1,
    "graph": 1.1,
}


def _short(text: str, limit: int = 18) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    for stop in ("。", "；", "，", ".", ";"):
        position = text.find(stop)
        if 0 <= position <= limit:
            return text[: position + 1]
    return text[:limit] + ("…" if len(text) > limit else "")


def _generated_label(block: PublicBlock, index: int) -> str:
    if block.type == "formula":
        return getattr(block, "label", "") or _short(getattr(block, "explanation", "")) or "公式"
    if block.type == "interactive":
        return getattr(block, "title", "") or "交互实验"
    if block.type == "table":
        return _short(getattr(block, "caption", ""), 24) or "数据表"
    if block.type == "svg":
        return _short(getattr(block, "alt", ""), 24) or "结构图"
    if block.type == "callout":
        kind = {
            "note": "说明",
            "warning": "注意",
            "limitation": "局限",
            "assumption": "假设",
        }.get(getattr(block, "kind", "note"), "说明")
        text = _short(getattr(block, "text", ""), 22)
        return f"{kind}：{text}" if text else kind
    if block.type == "check":
        return "学习检查"
    if block.type == "bullets":
        items = getattr(block, "items", [])
        return _short(items[0]) if items else "要点"
    if block.type == "paragraph":
        return _short(getattr(block, "text", "")) or "讲解"
    return _LABEL_BY_BLOCK.get(block.type, f"步骤 {index + 1}")


def _generated_scene(slide: PublicSlide, unit: LearningUnit) -> PlanScene:
    total_ms = max(1_000, int(round(unit.estimated_minutes * 60 * 1_000)))
    paired = sorted(
        enumerate(slide.body),
        key=lambda item: (item[1].type == "check", item[0]),
    )
    weights = [_STEP_WEIGHT.get(block.type, 1.0) for _index, block in paired]
    total_weight = sum(weights) or 1.0
    steps = [
        PlanStep(
            block=index,
            label=_generated_label(block, index),
            effect=_default_effect(block),
            duration_ms=max(MIN_STEP_MS, int(round(total_ms * weight / total_weight))),
        )
        for (index, block), weight in zip(paired, weights, strict=True)
    ]
    kinds = {block.type for block in slide.body}
    if kinds & {"svg", "figure", "diagram", "graph"}:
        scene_type = "structure"
    elif "formula" in kinds:
        scene_type = "formula"
    elif kinds & {"interactive", "table"}:
        scene_type = "data"
    else:
        scene_type = _SCENE_TYPE_BY_UNIT.get(unit.unit_type, "concept")
    return PlanScene(
        unit_id=unit.unit_id,
        scene_type=scene_type,
        objective_ids=[
            f"{unit.unit_id}-objective-{index:02d}" for index in range(len(unit.objectives))
        ],
        claim_refs=list(unit.claim_ids),
        steps=steps,
    )


def generate_scene_plan(master: CourseMaster, content: PublicContent) -> ScenePlan:
    """Derive a ScenePlan from delivered units (no hand-written plan needed)."""

    units: dict[str, Any] = {}
    for unit in master.units:
        for scene_id in unit.scene_ids:
            units[scene_id] = unit
    scenes: dict[str, PlanScene] = {}
    for slide in content.slides:
        scene_unit = units.get(slide.slide_id)
        if scene_unit is None:
            continue
        scenes[slide.slide_id] = _generated_scene(slide, scene_unit)
    return ScenePlan(scenes=scenes)


def merge_scene_plans(generated: ScenePlan, authored: ScenePlan | None) -> ScenePlan:
    """Authored steps win per scene; every other scene stays generated."""

    if authored is None:
        return generated
    scenes = dict(generated.scenes)
    for scene_id, authored_scene in authored.scenes.items():
        generated_scene = generated.scenes.get(scene_id)
        if generated_scene is not None and not authored_scene.unit_id:
            authored_scene = authored_scene.model_copy(update={"unit_id": generated_scene.unit_id})
        scenes[scene_id] = authored_scene
    return ScenePlan(schema_version=generated.schema_version, scenes=scenes)


@dataclass(frozen=True)
class SceneInputs:
    scenes: tuple[DeckScene, ...]
    master: CourseMaster
    generated_plan: ScenePlan
    effective_plan: ScenePlan


def build_scene_inputs(project_dir: Path, content: PublicContent) -> SceneInputs:
    outline = load_outline(project_dir)
    script = load_speaker_script(project_dir)
    ledger = load_evidence_ledger(project_dir)
    claims = load_claims(project_dir)
    master = materialize_course(
        content,
        outline=outline,
        script=script,
        ledger=ledger,
        claims=claims,
        blueprint=load_course_master(project_dir),
    )
    generated = generate_scene_plan(master, content)
    effective = merge_scene_plans(generated, load_scene_plan(project_dir))
    scenes = derive_deck_scenes(
        content,
        outline=outline,
        script=script,
        ledger=ledger,
        claims=claims,
        plan=effective,
    )
    return SceneInputs(
        scenes=scenes,
        master=master,
        generated_plan=generated,
        effective_plan=effective,
    )


def write_generated_plan(project_dir: Path, plan: ScenePlan) -> Path:
    path = project_dir / "internal" / "qa" / "scene_plan.generated.json"
    write_json(path, plan.model_dump(mode="json"))
    return path
