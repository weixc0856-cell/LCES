"""P2.4-B: per-template visual baselines and drift warnings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.visual_baseline import (
    BASELINE_DIR,
    baseline_path,
    build_baseline,
    compare_baseline,
)

HASH = "a" * 64


def _visual(
    *, foreground: float = 0.1, edges: float = 0.05, indices: tuple[int, ...] = (15,)
) -> dict:
    return {
        "schema_version": "1.0",
        "template": "title",
        "status": "pass",
        "sampled_frames": list(indices),
        "thresholds": {"min_foreground": 0.002, "min_edges": 0.001},
        "frames": [
            {
                "index": index,
                "foreground_ratio": foreground,
                "edge_ratio": edges,
                "blank": False,
            }
            for index in indices
        ],
    }


def _baseline(project: Path, **visual_kwargs) -> Path:
    return build_baseline(
        project,
        template="title",
        width=320,
        height=180,
        fps_num=30,
        fps_den=1,
        visual=_visual(**visual_kwargs),
        build_id="build-001",
        frame_sha256={15: HASH},
    )


def _compare(project: Path, **visual_kwargs):
    return compare_baseline(
        project,
        template="title",
        width=320,
        height=180,
        fps_num=30,
        fps_den=1,
        visual=_visual(**visual_kwargs),
        frame_sha256={15: HASH},
    )


def test_baseline_path_is_template_and_format_specific():
    path = baseline_path(Path("project"), "flow", 640, 360, 30, 1)
    assert path == Path("project") / BASELINE_DIR / "flow-640x360-30_1.json"


def test_missing_baseline_is_reported(tmp_path):
    comparison = _compare(tmp_path)
    assert comparison.status == "missing"
    assert comparison.as_dict()["path"].endswith("title-320x180-30_1.json")


def test_matching_baseline_is_not_a_warning(tmp_path):
    _baseline(tmp_path)
    comparison = _compare(tmp_path)
    assert comparison.status == "matched"
    assert comparison.warnings == []
    assert comparison.byte_identical is True


def test_byte_drift_alone_is_not_a_warning(tmp_path):
    _baseline(tmp_path)
    comparison = compare_baseline(
        tmp_path,
        template="title",
        width=320,
        height=180,
        fps_num=30,
        fps_den=1,
        visual=_visual(),
        frame_sha256={15: "b" * 64},
    )
    assert comparison.status == "matched"
    assert comparison.byte_identical is False


def test_metric_drift_warns(tmp_path):
    _baseline(tmp_path)
    comparison = _compare(tmp_path, foreground=0.3)
    assert comparison.status == "drifted"
    assert any("foreground drift" in warning for warning in comparison.warnings)
    assert "frame 15" in comparison.warnings[0]


def test_changed_sample_indices_require_a_new_baseline(tmp_path):
    _baseline(tmp_path)
    comparison = compare_baseline(
        tmp_path,
        template="title",
        width=320,
        height=180,
        fps_num=30,
        fps_den=1,
        visual=_visual(indices=(15, 30)),
        frame_sha256={15: HASH, 30: HASH},
    )
    assert comparison.status == "drifted"
    assert "sample frame indices changed" in comparison.warnings[0]


def test_a_failing_visual_report_cannot_become_a_baseline(tmp_path):
    visual = _visual()
    visual["status"] = "fail"
    with pytest.raises(ValueError, match="passing visual report"):
        build_baseline(
            tmp_path,
            template="title",
            width=320,
            height=180,
            fps_num=30,
            fps_den=1,
            visual=visual,
            build_id="build-001",
        )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    (project / "project.yaml").write_text("project_id: demo\ntitle: 示例\n", encoding="utf-8")
    (project / "internal" / "qa" / "visual_qa.json").write_text(
        json.dumps(_visual()), encoding="utf-8"
    )
    (project / "internal" / "qa" / "frame_manifest.json").write_text(
        json.dumps(
            {
                "build_id": "build-001",
                "width": 320,
                "height": 180,
                "fps_num": 30,
                "fps_den": 1,
                "frames": [{"index": 15, "sha256": HASH}],
            }
        ),
        encoding="utf-8",
    )
    return project


def test_cli_writes_a_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _project(tmp_path)
    result = CliRunner().invoke(
        app, ["visual-baseline", str(project), "--template", "title", "--note", "首次验收"]
    )
    assert result.exit_code == 0, result.output
    path = baseline_path(project, "title", 320, 180, 30, 1)
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["note"] == "首次验收"
    assert payload["frames"][0]["sha256"] == HASH


def test_cli_rejects_an_unknown_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _project(tmp_path)
    result = CliRunner().invoke(app, ["visual-baseline", str(project), "--template", "nope"])
    assert result.exit_code == 1
    assert "未知模板" in result.output
