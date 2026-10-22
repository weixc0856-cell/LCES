"""P2.1 real production entry: content drives `lces build` -> video -> assets.

Linux-only, like the other Motion Canvas E2E tests. The CI motion job sets
LCES_MC_E2E=1; a missing toolchain must fail rather than silently skip.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_studio import motion_canvas as mc
from content_studio.cli import app
from content_studio.models import FrameManifest
from content_studio.paths import BUILD_MARKER
from content_studio.utils import sha256_file
from content_studio.video_qa import verify_video_against_manifest
from content_studio.visuals import verify_build_assets

pytestmark = pytest.mark.motion


def _write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "content" / "scenes").mkdir(parents=True)
    (project / "project.yaml").write_text(
        "project_id: p21-demo\ntitle: P2.1 生产入口\n", encoding="utf-8"
    )
    public = {
        "project_id": "p21-demo",
        "title": "P2.1 生产入口",
        "slides": [
            {
                "slide_id": "slide-001",
                "title": "第一节",
                "body": [
                    {"type": "paragraph", "text": "正文"},
                    {
                        "type": "animation",
                        "scene_file": "content/scenes/course.json",
                        "alt": "课程动画",
                        "caption": "系统流程",
                    },
                ],
            }
        ],
    }
    (project / "content" / "public_content.json").write_text(
        json.dumps(public, ensure_ascii=False), encoding="utf-8"
    )
    reading = {
        "project_id": "p21-demo",
        "title": "P2.1 生产入口",
        "abstract": "生产入口测试。",
        "sections": [{"slide_id": "slide-001", "title": "第一节", "paragraphs": ["正文"]}],
    }
    (project / "content" / "reading_edition.json").write_text(
        json.dumps(reading, ensure_ascii=False), encoding="utf-8"
    )
    scene = {
        "scene_set": {
            "scenes": [
                {
                    "scene_id": "scene-001",
                    "scene_type": "title",
                    "duration_ms": 1000,
                    "data": {"title": "P2.1", "subtitle": "production entry"},
                }
            ]
        },
        "video": {
            "project_id": "p21-demo",
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
        },
    }
    (project / "content" / "scenes" / "course.json").write_text(json.dumps(scene), encoding="utf-8")
    return project


def test_lces_build_renders_animation_end_to_end(tmp_path, monkeypatch):
    if os.environ.get("LCES_MC_E2E") != "1":
        pytest.skip("set LCES_MC_E2E=1 on a Linux host with the pinned toolchain")
    if sys.platform != "linux":
        pytest.fail("LCES_MC_E2E=1 but the host is not Linux; P1/P2 are Linux-only")

    project = _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["build", str(project)])
    assert result.exit_code == 0, result.output

    video = project / "build" / "media" / "course.mp4"
    assert video.is_file() and video.stat().st_size > 0
    html = (project / "build" / "slides" / "index.html").read_text(encoding="utf-8")
    assert "<video controls" in html
    assert 'src="../media/course.mp4"' in html
    assert not (project / "build" / BUILD_MARKER).exists()

    qa_dir = project / "internal" / "qa"
    manifest = FrameManifest.model_validate_json(
        (qa_dir / "frame_manifest.json").read_text(encoding="utf-8")
    )
    assert verify_video_against_manifest(video, manifest) == []

    assets = json.loads((qa_dir / "visual_assets.json").read_text(encoding="utf-8"))
    animation = next(item for item in assets if item["asset_type"] == "animation")
    assert animation["build_id"] == manifest.build_id
    assert animation["source"] == "content/scenes/course.json"
    assert animation["output_hashes"]["build/media/course.mp4"] == sha256_file(video)
    assert animation["output_hashes"]["internal/qa/frame_manifest.json"] == sha256_file(
        qa_dir / "frame_manifest.json"
    )
    report = json.loads((qa_dir / "encode_report.json").read_text(encoding="utf-8"))
    assert report["video_sha256"] == sha256_file(video)
    assert verify_build_assets(project) == []
