"""The P9-B baseline verifier must detect any post-freeze change."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _verify():
    path = ROOT / "scripts" / "verify-course-baseline.py"
    spec = importlib.util.spec_from_file_location("verify_course_baseline", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.verify


def _write_baseline(root: Path, files: list[dict]) -> Path:
    baseline = root / "baseline.json"
    baseline.write_text(json.dumps({"files": files}), encoding="utf-8")
    return baseline


def test_matching_baseline_has_no_problems(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "course.json"
    target.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    baseline = _write_baseline(
        tmp_path, [{"path": "course.json", "present": True, "sha256": digest}]
    )

    assert _verify()(baseline, project) == []


def test_changed_file_is_reported(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "course.json"
    target.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    baseline = _write_baseline(
        tmp_path, [{"path": "course.json", "present": True, "sha256": digest}]
    )
    target.write_text('{"edited": true}', encoding="utf-8")

    assert _verify()(baseline, project) == ["changed after freeze: course.json"]


def test_missing_and_newly_appeared_files_are_reported(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    absent = project / "later.json"
    baseline = _write_baseline(
        tmp_path,
        [
            {"path": "gone.json", "present": True, "sha256": "0" * 64},
            {"path": "later.json", "present": False},
        ],
    )
    absent.write_text("{}", encoding="utf-8")

    problems = _verify()(baseline, project)

    assert "missing after freeze: gone.json" in problems
    assert "appeared after freeze: later.json" in problems
