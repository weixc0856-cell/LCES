"""P1 end-to-end renders: real editor, real Chromium, real frames.

Skipped by default because P1 is Linux-only. The CI job ``motion-canvas-p1``
sets ``LCES_MC_E2E=1`` and must fail, not skip, when the pinned toolchain is
missing -- a skipped integration test cannot discharge the gate.

Two configurations run in CI:

* smoke: 640x360, 30 frames -- the fast per-PR check;
* production: 1920x1080, 300 frames (10 s at 30 fps) -- the P1 acceptance
  configuration. The smoke run does not stand in for it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from content_studio import motion_canvas as mc
from content_studio.frame_manifest import png_problems
from content_studio.models import VisualSpec
from content_studio.renderers import RenderContext

pytestmark = pytest.mark.motion


def _spec(*, duration_ms: int, width: int, height: int) -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": "title",
        "duration_ms": duration_ms,
        "data": {"title": "LCES P1", "subtitle": "end-to-end"},
    }
    video = {
        "project_id": "demo",
        "video_id": "course-v1",
        "content_version": "v1",
        "width": width,
        "height": height,
        "fps_num": 30,
        "fps_den": 1,
        "scene_ids": ["scene-001"],
        "output_path": "build/media/course.mp4",
        "renderer": mc.MotionCanvasRenderer.name,
        "renderer_version": mc.MotionCanvasRenderer.version,
    }
    return VisualSpec(
        visual_id="course-v1",
        visual_type="animation",
        renderer=mc.MotionCanvasRenderer.name,
        data={"scene_set": {"scenes": [scene]}, "video": video},
    )


def _render(tmp_path: Path, spec: VisualSpec, *, max_render_ms: int) -> dict:
    if os.environ.get("LCES_MC_E2E") != "1":
        pytest.skip("set LCES_MC_E2E=1 on a Linux host with the pinned toolchain")

    renderer = mc.MotionCanvasRenderer(max_render_ms=max_render_ms)
    problems = renderer.check_environment()
    assert not problems, (
        "P1 E2E needs the pinned toolchain (a missing dependency is a failure, "
        "not a skip): " + "; ".join(problems)
    )

    result = renderer.render(spec, RenderContext(output_dir=tmp_path))
    assert result.status == "completed"
    assert result.build_id

    report_path = next(path for path in result.artifacts if path.name == "report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["finished"] is True
    assert report["terminal"] == "completed"
    assert report["error_code"] == ""
    # Offline isolation is an OS-level claim proved in P1.4; P1.1 only records
    # what the driver observed. P0 saw failed external attempts even with no
    # network, so an empty list is not a valid assertion here.
    assert isinstance(report["external_requests"], list)
    return report


def test_smoke_config_renders_30_frames(tmp_path):
    report = _render(
        tmp_path, _spec(duration_ms=1000, width=640, height=360), max_render_ms=180_000
    )
    assert report["frames"] == 30


def test_production_config_renders_300_frames_at_1080p(tmp_path):
    report = _render(
        tmp_path,
        _spec(duration_ms=10_000, width=1920, height=1080),
        max_render_ms=300_000,
    )
    assert report["frames"] == 300
    frames = sorted(tmp_path.rglob("000000.png"))[0].parent
    assert png_problems(frames / "000000.png", 1920, 1080) == []
    assert png_problems(frames / "000299.png", 1920, 1080) == []
