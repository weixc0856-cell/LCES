"""Materialise LearningUnits from the delivered course.

The paper coverage blueprint in ``internal/course_master.json`` says which paper
elements the course intends to cover. This module produces the *delivered* view:
one LearningUnit per scene, linked to the scene instead of copying its body and
narration. The generated master keeps the blueprint chapters/units/coverage and
adds a delivered chapter, so coverage stays valid while the generation pipeline
gets a unit layer that maps one-to-one to scenes.

The output is deterministic and carries an input fingerprint per unit. No
timestamps are written, so an unchanged course produces the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from content_studio.content import load_outline, load_speaker_script
from content_studio.evidence import load_claims
from content_studio.models import (
    Claim,
    ContentOutline,
    CourseChapter,
    CourseMaster,
    EvidenceLedger,
    LearningUnit,
    PublicContent,
    PublicSlide,
    SpeakerScript,
    UnitType,
)
from content_studio.planning import load_course_master
from content_studio.research import load_evidence_ledger
from content_studio.utils import sha256_text, write_json

MATERIALIZED_PATH = Path("internal") / "plan" / "course_master.generated.json"
DELIVERED_CHAPTER_BASE = 900
DELIVERED_UNIT_BASE = 100

_VISUAL_LABELS = {
    "svg": "结构图",
    "formula": "公式推导",
    "table": "数据表",
    "interactive": "交互实验",
    "figure": "图示",
    "chart": "图表",
    "diagram": "示意图",
    "graph": "关系图",
}


def _unit_type(slide: PublicSlide) -> UnitType:
    kinds = {block.type for block in slide.body}
    if kinds & {"svg", "figure", "diagram", "graph"}:
        return "concept"
    if "formula" in kinds:
        return "formula"
    if kinds & {"interactive", "table"}:
        return "experiment"
    return "concept"


def _visual_requirements(slide: PublicSlide) -> list[str]:
    labels: list[str] = []
    for block in slide.body:
        label = _VISUAL_LABELS.get(block.type)
        if label and label not in labels:
            labels.append(label)
    return labels


def _ledger_claims(evidence_ids: list[str], ledger: EvidenceLedger | None) -> list[str]:
    if ledger is None:
        return []
    wanted = set(evidence_ids)
    return list(
        dict.fromkeys(record.claim_id for record in ledger.records if record.evidence_id in wanted)
    )


def unit_fingerprint(
    slide: PublicSlide,
    narration: str,
    claim_ids: list[str],
    evidence_ids: list[str],
    *,
    claims: list[Claim] | None,
    ledger: EvidenceLedger | None,
) -> str:
    claims_by_id = {claim.claim_id: claim for claim in claims or []}
    evidence_by_id = {
        record.evidence_id: record for record in (ledger.records if ledger is not None else [])
    }
    payload = {
        "scene_version": "1",
        "slide": slide.model_dump(mode="json"),
        "narration_sha256": sha256_text(narration),
        "claims": [
            claims_by_id[item].model_dump(mode="json") for item in claim_ids if item in claims_by_id
        ],
        "evidence": [
            evidence_by_id[item].model_dump(mode="json")
            for item in evidence_ids
            if item in evidence_by_id
        ],
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _delivered_chapter_id(blueprint: CourseMaster | None) -> str:
    existing = {chapter.chapter_id for chapter in blueprint.chapters} if blueprint else set()
    number = DELIVERED_CHAPTER_BASE
    while f"chapter-{number:03d}" in existing:
        number += 1
    return f"chapter-{number:03d}"


def _delivered_unit_start(blueprint: CourseMaster | None) -> int:
    if blueprint is None:
        return DELIVERED_UNIT_BASE + 1
    numbers = [int(unit.unit_id.split("-")[1]) for unit in blueprint.units]
    return max(DELIVERED_UNIT_BASE + 1, (max(numbers) + 1) if numbers else DELIVERED_UNIT_BASE + 1)


def materialize_course(
    content: PublicContent,
    *,
    outline: ContentOutline | None = None,
    script: SpeakerScript | None = None,
    ledger: EvidenceLedger | None = None,
    claims: list[Claim] | None = None,
    blueprint: CourseMaster | None = None,
) -> CourseMaster:
    """Build the delivered CourseMaster: blueprint structure plus scene units."""

    sections = {section.slide_id: section for section in (outline.sections if outline else [])}
    narrations = {section.slide_id: section for section in (script.sections if script else [])}
    chapter_id = _delivered_chapter_id(blueprint)
    unit_start = _delivered_unit_start(blueprint)
    units: list[LearningUnit] = []
    previous_unit_id = ""

    for index, slide in enumerate(content.slides):
        section = sections.get(slide.slide_id)
        script_section = narrations.get(slide.slide_id)
        evidence_ids = list(section.evidence_ids) if section is not None else []
        claim_ids = _ledger_claims(evidence_ids, ledger)
        narration = script_section.narration if script_section is not None else ""
        if script_section is not None and script_section.estimated_seconds:
            minutes = max(0.5, script_section.estimated_seconds / 60)
        elif section is not None and section.estimated_minutes:
            minutes = section.estimated_minutes
        else:
            minutes = 1.0
        unit_id = f"unit-{unit_start + index:03d}"
        units.append(
            LearningUnit(
                unit_id=unit_id,
                chapter_id=chapter_id,
                title=slide.title,
                unit_type=_unit_type(slide),
                objectives=list(section.learning_objectives) if section is not None else [],
                prerequisites=[previous_unit_id] if previous_unit_id else [],
                key_concepts=list(section.key_points) if section is not None else [],
                evidence_ids=evidence_ids,
                claim_ids=claim_ids,
                visual_requirements=_visual_requirements(slide),
                estimated_minutes=round(minutes, 2),
                scene_ids=[slide.slide_id],
                input_sha256=unit_fingerprint(
                    slide,
                    narration,
                    claim_ids,
                    evidence_ids,
                    claims=claims,
                    ledger=ledger,
                ),
                notes=(
                    "materialised from the delivered slide; "
                    "the scene contract is the content source"
                ),
            )
        )
        previous_unit_id = unit_id

    chapters = list(blueprint.chapters) if blueprint is not None else []
    chapters.append(
        CourseChapter(
            chapter_id=chapter_id,
            title="已交付场景",
            objectives=[objective for unit in units for objective in unit.objectives],
            unit_ids=[unit.unit_id for unit in units],
            source_ids=sorted({source for slide in content.slides for source in slide.source_ids}),
        )
    )
    all_units = [*(blueprint.units if blueprint is not None else []), *units]
    return CourseMaster(
        project_id=content.project_id,
        title=content.title,
        language=content.language,
        audience=content.audience or (blueprint.audience if blueprint is not None else ""),
        prerequisites=list(blueprint.prerequisites) if blueprint is not None else [],
        chapters=chapters,
        units=all_units,
        coverage=list(blueprint.coverage) if blueprint is not None else [],
        source_ids=list(blueprint.source_ids) if blueprint is not None else [],
        references=list(blueprint.references) if blueprint is not None else [],
        status="draft",
    )


def materialize_project_course(project_dir: Path, content: PublicContent) -> CourseMaster:
    return materialize_course(
        content,
        outline=load_outline(project_dir),
        script=load_speaker_script(project_dir),
        ledger=load_evidence_ledger(project_dir),
        claims=load_claims(project_dir),
        blueprint=load_course_master(project_dir),
    )


def write_materialized_course(project_dir: Path, master: CourseMaster) -> Path:
    path = project_dir / MATERIALIZED_PATH
    write_json(path, master)
    return path


def load_materialized_course(project_dir: Path) -> CourseMaster | None:
    path = project_dir / MATERIALIZED_PATH
    if not path.is_file():
        return None
    try:
        return CourseMaster.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def delivered_units(master: CourseMaster) -> list[LearningUnit]:
    return [unit for unit in master.units if unit.scene_ids]


def stale_units(project_dir: Path, content: PublicContent, master: CourseMaster) -> list[str]:
    """Units whose stored fingerprint no longer matches the current inputs."""

    outline = load_outline(project_dir)
    script = load_speaker_script(project_dir)
    ledger = load_evidence_ledger(project_dir)
    claims = load_claims(project_dir)
    slides = {slide.slide_id: slide for slide in content.slides}
    sections = {section.slide_id: section for section in (outline.sections if outline else [])}
    narrations = {section.slide_id: section for section in (script.sections if script else [])}
    stale: list[str] = []
    for unit in delivered_units(master):
        scene_id = unit.scene_ids[0]
        slide = slides.get(scene_id)
        if slide is None:
            stale.append(unit.unit_id)
            continue
        section = sections.get(scene_id)
        evidence_ids = list(section.evidence_ids) if section is not None else []
        claim_ids = _ledger_claims(evidence_ids, ledger)
        narration = narrations[scene_id].narration if scene_id in narrations else ""
        current = unit_fingerprint(
            slide,
            narration,
            claim_ids,
            evidence_ids,
            claims=claims,
            ledger=ledger,
        )
        if current != unit.input_sha256:
            stale.append(unit.unit_id)
    return stale


def affected_units(master: CourseMaster, claim_id: str) -> list[str]:
    return [unit.unit_id for unit in delivered_units(master) if claim_id in unit.claim_ids]
