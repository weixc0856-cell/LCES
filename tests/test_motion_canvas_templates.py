"""Real renders for the P2.2 flow and compare templates (Linux CI)."""

from __future__ import annotations

import json
import os
import sys

import pytest

from content_studio import motion_canvas as mc
from content_studio.models import FrameManifest, VisualSpec
from content_studio.renderers import RenderContext
from content_studio.video_qa import verify_video_against_manifest

pytestmark = pytest.mark.motion


def _flow_data() -> dict:
    return {
        "title": "请求处理流程",
        "subtitle": "从网关到存储",
        "direction": "lr",
        "nodes": [
            {"id": "gateway", "label": "网关", "kind": "start"},
            {"id": "auth", "label": "鉴权", "kind": "step"},
            {"id": "store", "label": "存储", "kind": "end"},
        ],
        "edges": [
            {"from": "gateway", "to": "auth"},
            {"from": "auth", "to": "store", "label": "写入"},
        ],
    }


def _compare_data() -> dict:
    return {
        "title": "两种方案",
        "subtitle": "吞吐与复杂度",
        "left": {"title": "方案 A", "items": ["实现简单", "吞吐稳定"]},
        "right": {"title": "方案 B", "items": ["扩展性好", "运维复杂"]},
    }


def _spec(scene_type: str, data: dict) -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": scene_type,
        "duration_ms": 1000,
        "data": data,
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


@pytest.mark.parametrize(
    ("scene_type", "data"),
    [("flow", _flow_data()), ("compare", _compare_data())],
)
def test_template_renders_30_frames(tmp_path, scene_type, data):
    if os.environ.get("LCES_MC_E2E") != "1":
        pytest.skip("set LCES_MC_E2E=1 on a Linux host with the pinned toolchain")
    if sys.platform != "linux":
        pytest.fail("LCES_MC_E2E=1 but the host is not Linux; P2 is Linux-only")

    renderer = mc.MotionCanvasRenderer(max_render_ms=180_000)
    problems = renderer.check_environment()
    assert not problems, (
        "P2 E2E needs the pinned toolchain (a missing dependency is a failure, "
        "not a skip): " + "; ".join(problems)
    )
    result = renderer.render(
        _spec(scene_type, data),
        RenderContext(output_dir=tmp_path, project_dir=tmp_path / "project", publish=True),
    )
    assert result.status == "completed"
    report_path = next(path for path in result.artifacts if path.name == "report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["frames"] == 30
    assert report["terminal"] == "completed"

    video = tmp_path / "project" / "build" / "media" / "course.mp4"
    assert video.is_file()
    manifest_path = next((tmp_path / "project").rglob("frame_manifest.json"))
    manifest = FrameManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert manifest.total_frames == 30
    assert (manifest.width, manifest.height) == (640, 360)
    assert verify_video_against_manifest(video, manifest) == []
    first = tmp_path / "project" / "build" / "motion"
    assert any(first.rglob("000000.png"))
    assert any(first.rglob("000029.png"))
