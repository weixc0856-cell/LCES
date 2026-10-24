"""Coverage planning: map paper elements to the units that teach them.

The planner is deterministic. It does not decide what to teach; it records
where the units in ``CourseMaster`` cover the elements in ``PaperMap``, and
reports required elements with no teaching home. A hand-authored coverage
matrix keeps its notes when regenerated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from content_studio.models import (
    CourseMaster,
    CoverageEntry,
    CoverageMatrix,
    CoverageStatus,
    PaperMap,
)

PAPER_MAP_PATH = Path("internal") / "plan" / "paper_map.json"
COVERAGE_PATH = Path("internal") / "plan" / "coverage_matrix.json"
MASTER_PATH = Path("internal") / "course_master.json"


def _load[ModelT: BaseModel](model: type[ModelT], path: Path) -> ModelT | None:
    if not path.exists():
        return None
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def load_paper_map(project_dir: Path) -> PaperMap | None:
    return _load(PaperMap, project_dir / PAPER_MAP_PATH)


def load_coverage_matrix(project_dir: Path) -> CoverageMatrix | None:
    return _load(CoverageMatrix, project_dir / COVERAGE_PATH)


def load_course_master(project_dir: Path) -> CourseMaster | None:
    return _load(CourseMaster, project_dir / MASTER_PATH)


def paper_map_sha256(project_dir: Path) -> str:
    path = project_dir / PAPER_MAP_PATH
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unknown_paper_items(paper_map: PaperMap, master: CourseMaster) -> list[str]:
    """Unit references to paper elements that do not exist in the map."""

    known = {element.paper_item_id for element in paper_map.elements}
    return sorted(
        {
            item_id
            for unit in master.units
            for item_id in unit.paper_item_ids
            if item_id not in known
        }
    )


def build_coverage(
    paper_map: PaperMap,
    master: CourseMaster,
    *,
    paper_map_sha256: str = "",
    previous: CoverageMatrix | None = None,
) -> CoverageMatrix:
    by_item: dict[str, list[str]] = {}
    for unit in master.units:
        for item_id in unit.paper_item_ids:
            units = by_item.setdefault(item_id, [])
            if unit.unit_id not in units:
                units.append(unit.unit_id)

    previous_notes = (
        {entry.paper_item_id: entry.notes for entry in previous.entries}
        if previous is not None
        else {}
    )
    entries: list[CoverageEntry] = []
    for element in paper_map.elements:
        units = by_item.get(element.paper_item_id, [])
        status: CoverageStatus
        if units:
            status = "covered"
        elif element.required:
            status = "missing"
        else:
            status = "not_applicable"
        entries.append(
            CoverageEntry(
                paper_item_id=element.paper_item_id,
                required=element.required,
                covered_by=units,
                status=status,
                evidence_ids=list(element.evidence_ids),
                notes=previous_notes.get(element.paper_item_id, ""),
            )
        )
    return CoverageMatrix(
        project_id=paper_map.project_id,
        paper_map_sha256=paper_map_sha256,
        entries=entries,
    )


def coverage_gaps(paper_map: PaperMap, matrix: CoverageMatrix) -> list[str]:
    """Required paper elements with no unit teaching them."""

    entries = {entry.paper_item_id: entry for entry in matrix.entries}
    gaps: list[str] = []
    for element in paper_map.elements:
        if not element.required:
            continue
        entry = entries.get(element.paper_item_id)
        if entry is None or entry.status not in {"covered", "partial"} or not entry.covered_by:
            gaps.append(element.paper_item_id)
    return gaps
