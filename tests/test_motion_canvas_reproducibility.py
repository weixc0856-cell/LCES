"""P2.4-C: two real renders in the same environment (opt-in).

Set ``LCES_MC_REPRO=1`` on a Linux host with the pinned toolchain. The test
does not assert byte identity: it writes a report with the measured rate,
the visual deltas and the environment, so a reviewer can judge the claim.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from content_studio import motion_canvas as mc
from content_studio.models import FrameManifest, VisualSpec
from content_studio.paths import ensure_project_layout
from content_studio.renderers import RenderContext
from content_studio.reproducibility import build_report

pytestmark = pytest.mark.motion

requires_repro = pytest.mark.skipif(
    os.environ.get("LCES_MC_REPRO") != "1",
    reason="set LCES_MC_REPRO=1 to run the two-render measurement",
)


def _spec() -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": "title",
        "duration_ms": 1000,
        "data": {"title": "复现性", "subtitle": "两次渲染"},
    }
    video = {
        "project_id": "repro",
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


@requires_repro
def test_two_renders_are_measured_not_promised(tmp_path, monkeypatch):
    project = ensure_project_layout(tmp_path / "project")
    spec = _spec()
    build_dirs: list[Path] = []
    for build_id in ("repro-a", "repro-b"):
        monkeypatch.setenv("LCES_BUILD_ID", build_id)
        renderer = mc.MotionCanvasRenderer(max_render_ms=180_000)
        result = renderer.render(
            spec,
            RenderContext(project_dir=project, output_dir=project / "build", publish=True),
        )
        assert result.status == "completed"
        build_dirs.append(project / "build" / "motion" / build_id)

    manifests = [
        FrameManifest.model_validate_json(
            (build / "frame_manifest.json").read_text(encoding="utf-8")
        )
        for build in build_dirs
    ]
    visuals = [
        json.loads((build / "visual_qa.json").read_text(encoding="utf-8")) for build in build_dirs
    ]
    report = build_report(
        scene={"type": "title", "width": 640, "height": 360, "frames": 30},
        first=manifests[0],
        second=manifests[1],
        first_visual=visuals[0],
        second_visual=visuals[1],
    )
    output = Path(os.environ.get("LCES_REPRO_OUT", str(project / "build" / "reproducibility.json")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    assert report["frames"]["total"] == 30
    assert visuals[0]["status"] == "pass"
    assert visuals[1]["status"] == "pass"
    assert output.is_file()
    print(json.dumps(report, indent=2, ensure_ascii=False))
