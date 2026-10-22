"""P1 end-to-end render: real editor, real Chromium, real frames.

Skipped by default because P1 is Linux-only. The CI job ``motion-canvas-p1``
sets ``LCES_MC_E2E=1`` and must fail, not skip, when the pinned toolchain is
missing -- a skipped integration test cannot discharge the gate.
"""

from __future__ import annotations

import json
import os

import pytest

from content_studio import motion_canvas as mc
from content_studio.models import VisualSpec
from content_studio.renderers import RenderContext

pytestmark = pytest.mark.motion


def _spec() -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": "title",
        "duration_ms": 1000,
        "data": {"title": "LCES P1", "subtitle": "end-to-end"},
    }
    video = {
        "project_id": "demo",
        "video_id": "course-v1",
        "content_version": "v1",
        "width": 640,
        "height": 360,
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


def test_title_scene_renders_with_the_pinned_toolchain(tmp_path):
    if os.environ.get("LCES_MC_E2E") != "1":
        pytest.skip("set LCES_MC_E2E=1 on a Linux host with the pinned toolchain")

    renderer = mc.MotionCanvasRenderer(max_render_ms=180_000)
    problems = renderer.check_environment()
    assert not problems, (
        "P1 E2E needs the pinned toolchain (a missing dependency is a failure, "
        "not a skip): " + "; ".join(problems)
    )

    result = renderer.render(_spec(), RenderContext(output_dir=tmp_path))
    assert result.status == "completed"
    assert result.build_id

    report_path = result.artifacts[0]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["finished"] is True
    assert report["frames"] == 30
    assert report["terminal"] == "completed"
    assert report["error_code"] == ""
    # Offline isolation is an OS-level claim proved in P1.4; P1.1 only records
    # what the driver observed. P0 saw failed external attempts even with no
    # network, so an empty list is not a valid assertion here.
    assert isinstance(report["external_requests"], list)
