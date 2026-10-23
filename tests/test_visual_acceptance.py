"""P2.4-D: human visual acceptance and its release gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.validation import _visual_acceptance_checks
from content_studio.visual_acceptance import (
    RECORD_PATH,
    acceptance_problem,
    current_toolchain,
    load_records,
    record_acceptance,
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    (project / "project.yaml").write_text("project_id: demo\ntitle: 示例\n", encoding="utf-8")
    return project


def _visual(project: Path, *, status: str = "pass", template: str = "title") -> Path:
    path = project / "internal" / "qa" / "visual_qa.json"
    path.write_text(
        json.dumps({"schema_version": "1.0", "status": status, "template": template}),
        encoding="utf-8",
    )
    return path


def test_toolchain_lists_the_version_inputs():
    toolchain = current_toolchain()
    assert set(toolchain) == {
        "node_version",
        "motion_canvas_version",
        "playwright_version",
        "ffmpeg_version",
    }
    assert toolchain["node_version"]


def test_record_acceptance_appends_and_current_toolchain_matches(tmp_path):
    project = _project(tmp_path)
    path = record_acceptance(
        project, template="title", reviewer="alice", frames=[15, 30], verdict="pass"
    )
    assert path == project / RECORD_PATH
    records = load_records(project)
    assert len(records) == 1
    assert records[0]["reviewer"] == "alice"
    assert records[0]["frames"] == [15, 30]
    assert records[0]["toolchain"] == current_toolchain()
    assert acceptance_problem(project, template="title") == ""


def test_missing_record_is_reported(tmp_path):
    project = _project(tmp_path)
    assert "没有人工视觉验收记录" in acceptance_problem(project, template="title")


def test_wrong_template_or_toolchain_or_verdict_fails(tmp_path):
    project = _project(tmp_path)
    record_acceptance(project, template="flow", reviewer="alice", frames=[15], verdict="pass")
    assert "没有与当前工具链匹配" in acceptance_problem(project, template="title")

    records = load_records(project)
    records[0]["template"] = "title"
    records[0]["toolchain"] = {**current_toolchain(), "node_version": "0.0.0"}
    (project / RECORD_PATH).write_text(
        json.dumps({"schema_version": "1.0", "records": records}), encoding="utf-8"
    )
    assert "没有与当前工具链匹配" in acceptance_problem(project, template="title")

    record_acceptance(project, template="title", reviewer="bob", frames=[15], verdict="fail")
    assert "没有与当前工具链匹配" in acceptance_problem(project, template="title")


def test_record_acceptance_rejects_incomplete_input(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="reviewer"):
        record_acceptance(project, template="title", reviewer=" ", frames=[1], verdict="pass")
    with pytest.raises(ValueError, match="frame"):
        record_acceptance(project, template="title", reviewer="a", frames=[], verdict="pass")
    with pytest.raises(ValueError, match="verdict"):
        record_acceptance(project, template="title", reviewer="a", frames=[1], verdict="ok")


def test_gate_warns_without_visual_evidence(tmp_path):
    project = _project(tmp_path)
    checks = _visual_acceptance_checks(project)
    assert checks[0].status == "warn"
    assert checks[0].blocking is False


def test_gate_fails_without_a_matching_acceptance(tmp_path):
    project = _project(tmp_path)
    _visual(project)
    checks = _visual_acceptance_checks(project)
    assert checks[0].status == "fail"
    assert checks[0].blocking is True


def test_gate_fails_when_the_visual_check_failed(tmp_path):
    project = _project(tmp_path)
    _visual(project, status="fail")
    checks = _visual_acceptance_checks(project)
    assert checks[0].status == "fail"
    assert "人工验收不能替代" in checks[0].message


def test_gate_passes_with_a_matching_acceptance(tmp_path):
    project = _project(tmp_path)
    _visual(project)
    record_acceptance(project, template="title", reviewer="alice", frames=[15], verdict="pass")
    checks = _visual_acceptance_checks(project)
    assert checks[0].status == "pass"


def test_cli_records_an_acceptance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _project(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "accept-visual",
            str(project),
            "--template",
            "title",
            "--by",
            "alice",
            "--frame",
            "15",
            "--note",
            "抽看中段",
        ],
    )
    assert result.exit_code == 0, result.output
    records = load_records(project)
    assert records[0]["reviewer"] == "alice"
    assert records[0]["note"] == "抽看中段"


def test_cli_requires_a_frame_and_a_known_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _project(tmp_path)
    missing = CliRunner().invoke(
        app, ["accept-visual", str(project), "--template", "title", "--by", "alice"]
    )
    assert missing.exit_code == 1
    assert "至少提供一个 --frame" in missing.output
    unknown = CliRunner().invoke(
        app,
        ["accept-visual", str(project), "--template", "nope", "--by", "alice", "--frame", "1"],
    )
    assert unknown.exit_code == 1
    assert "未知模板" in unknown.output
