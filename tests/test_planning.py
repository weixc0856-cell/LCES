from __future__ import annotations

import hashlib
from pathlib import Path

from content_studio.models import CourseMaster, CoverageMatrix, PaperMap
from content_studio.planning import (
    build_coverage,
    coverage_gaps,
    load_course_master,
    load_coverage_matrix,
    load_paper_map,
    paper_map_sha256,
    unknown_paper_items,
)
from content_studio.utils import write_json
from content_studio.validation import _coverage_checks

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "course_plan" / "attention"


def _fixtures() -> tuple[PaperMap, CoverageMatrix, CourseMaster]:
    paper_map = PaperMap.model_validate_json(
        (FIXTURE / "paper_map.json").read_text(encoding="utf-8")
    )
    coverage = CoverageMatrix.model_validate_json(
        (FIXTURE / "coverage_matrix.json").read_text(encoding="utf-8")
    )
    master = CourseMaster.model_validate_json(
        (FIXTURE / "course_master.json").read_text(encoding="utf-8")
    )
    return paper_map, coverage, master


def test_build_coverage_reproduces_the_attention_matrix():
    paper_map, coverage, master = _fixtures()
    digest = hashlib.sha256((FIXTURE / "paper_map.json").read_bytes()).hexdigest()

    rebuilt = build_coverage(paper_map, master, paper_map_sha256=digest, previous=coverage)

    assert rebuilt == coverage


def test_missing_required_element_is_reported_as_a_gap():
    paper_map, coverage, master = _fixtures()
    modified_units = [
        unit.model_copy(
            update={"paper_item_ids": [item for item in unit.paper_item_ids if item != "paper-025"]}
        )
        if unit.unit_id == "unit-020"
        else unit
        for unit in master.units
    ]
    modified = master.model_copy(update={"units": modified_units})

    rebuilt = build_coverage(paper_map, modified)
    gaps = coverage_gaps(paper_map, rebuilt)

    assert gaps == ["paper-025"]
    assert (
        next(entry for entry in rebuilt.entries if entry.paper_item_id == "paper-025").status
        == "missing"
    )


def test_units_referencing_unknown_paper_items_are_detected():
    paper_map, _, master = _fixtures()
    modified_units = [
        master.units[0].model_copy(
            update={"paper_item_ids": [*master.units[0].paper_item_ids, "paper-999"]}
        ),
        *master.units[1:],
    ]
    modified = master.model_copy(update={"units": modified_units})

    assert unknown_paper_items(paper_map, modified) == ["paper-999"]


def _write_plan(
    project: Path,
    *,
    paper_map: PaperMap | None = None,
    coverage: CoverageMatrix | None = None,
    master: CourseMaster | None = None,
) -> None:
    default_paper, default_coverage, default_master = _fixtures()
    (project / "internal" / "plan").mkdir(parents=True, exist_ok=True)
    write_json(project / "internal" / "plan" / "paper_map.json", paper_map or default_paper)
    write_json(
        project / "internal" / "plan" / "coverage_matrix.json",
        coverage or default_coverage,
    )
    write_json(project / "internal" / "course_master.json", master or default_master)


def test_coverage_gate_passes_on_the_blueprint(tmp_path: Path):
    _write_plan(tmp_path)
    checks = _coverage_checks(tmp_path)

    assert len(checks) == 1
    assert checks[0].status == "pass"
    assert checks[0].check_id == "coverage_matrix_complete"


def test_coverage_gate_fails_when_a_required_element_is_uncovered(tmp_path: Path):
    paper_map, coverage, master = _fixtures()
    modified_units = [
        unit.model_copy(
            update={"paper_item_ids": [item for item in unit.paper_item_ids if item != "paper-025"]}
        )
        if unit.unit_id == "unit-020"
        else unit
        for unit in master.units
    ]
    modified = build_coverage(
        paper_map,
        master.model_copy(update={"units": modified_units}),
        paper_map_sha256=paper_map_sha256_from_fixture(),
    )
    _write_plan(tmp_path, coverage=modified, master=master)

    checks = _coverage_checks(tmp_path)

    assert checks[0].status == "fail"
    assert "paper-025" in checks[0].message


def test_coverage_gate_detects_a_stale_matrix(tmp_path: Path):
    paper_map, coverage, master = _fixtures()
    changed = paper_map.model_copy(
        update={
            "elements": [
                *paper_map.elements[:-1],
                paper_map.elements[-1].model_copy(update={"title": "changed"}),
            ]
        }
    )
    _write_plan(tmp_path, paper_map=changed, coverage=coverage, master=master)

    checks = _coverage_checks(tmp_path)

    assert checks[0].status == "fail"
    assert "另一版" in checks[0].message


def test_coverage_gate_is_not_run_without_planning_data(tmp_path: Path):
    checks = _coverage_checks(tmp_path)

    assert checks[0].status == "not_run"
    assert checks[0].blocking is False


def test_planning_loaders_return_none_for_absent_files(tmp_path: Path):
    assert load_paper_map(tmp_path) is None
    assert load_coverage_matrix(tmp_path) is None
    assert load_course_master(tmp_path) is None
    assert paper_map_sha256(tmp_path) == ""


def paper_map_sha256_from_fixture() -> str:
    return hashlib.sha256((FIXTURE / "paper_map.json").read_bytes()).hexdigest()
