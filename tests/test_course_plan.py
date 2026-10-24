"""The Attention blueprint is planning data, not generated content.

These tests keep it honest: every required paper element has a teaching
home, nothing claims to be verified, and the coverage file is tied to the
exact paper map it was written against.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from content_studio.models import CourseMaster, CoverageMatrix, PaperMap

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "course_plan" / "attention"
PAPER_MAP = FIXTURE / "paper_map.json"
COVERAGE = FIXTURE / "coverage_matrix.json"
MASTER = FIXTURE / "course_master.json"

# Elements the plan names as non-negotiable for this paper.
KEY_ITEMS = [
    "paper-001",  # abstract and reported results
    "paper-006",  # scaled dot-product attention
    "paper-007",  # attention formula
    "paper-008",  # multi-head attention
    "paper-009",  # multi-head formula
    "paper-013",  # positional encoding
    "paper-014",  # positional encoding formula
    "paper-016",  # Table 1
    "paper-025",  # Table 2
    "paper-027",  # Table 3
    "paper-030",  # limitations
]


def _load(model, path: Path):
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def test_blueprint_validates_and_stays_planned():
    master = _load(CourseMaster, MASTER)

    assert len(master.chapters) == 12
    assert len(master.units) == 25
    assert master.status == "draft"
    assert all(unit.status == "planned" for unit in master.units)
    assert all(not unit.body and not unit.narration for unit in master.units)
    assert all(unit.revision == 0 for unit in master.units)

    planned_minutes = sum(unit.estimated_minutes for unit in master.units)
    assert 60 <= planned_minutes <= 90


def test_every_required_paper_element_has_a_teaching_home():
    paper = _load(PaperMap, PAPER_MAP)
    coverage = _load(CoverageMatrix, COVERAGE)

    entries = {entry.paper_item_id: entry for entry in coverage.entries}
    missing = [
        element.paper_item_id
        for element in paper.elements
        if element.required and element.paper_item_id not in entries
    ]
    assert missing == []

    uncovered = [
        entry.paper_item_id
        for entry in coverage.entries
        if entry.required and entry.status == "missing"
    ]
    assert uncovered == []

    for item_id in KEY_ITEMS:
        element = next(item for item in paper.elements if item.paper_item_id == item_id)
        assert element.required is True
        assert entries[item_id].covered_by


def test_blueprint_does_not_claim_verification_or_evidence():
    paper = _load(PaperMap, PAPER_MAP)
    master = _load(CourseMaster, MASTER)

    assert all(element.status != "verified" for element in paper.elements)
    assert any(element.status == "not_found" for element in paper.elements)
    assert all(not unit.evidence_ids for unit in master.units)
    assert all(not unit.claim_ids for unit in master.units)


def test_coverage_is_pinned_to_the_exact_paper_map():
    coverage = _load(CoverageMatrix, COVERAGE)
    digest = hashlib.sha256(PAPER_MAP.read_bytes()).hexdigest()

    assert coverage.paper_map_sha256 == digest


def test_master_coverage_matches_the_coverage_matrix():
    coverage = _load(CoverageMatrix, COVERAGE)
    master = _load(CourseMaster, MASTER)

    assert master.coverage == coverage.entries


def test_blueprint_units_reference_known_paper_elements():
    paper = _load(PaperMap, PAPER_MAP)
    master = _load(CourseMaster, MASTER)
    known = {element.paper_item_id for element in paper.elements}

    unknown = {
        item_id for unit in master.units for item_id in unit.paper_item_ids if item_id not in known
    }
    assert unknown == set()


def test_blueprint_paths_are_present():
    for path in (PAPER_MAP, COVERAGE, MASTER):
        assert path.is_file(), f"missing blueprint artifact: {path}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
