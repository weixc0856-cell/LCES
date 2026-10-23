"""P3-C: fault injection on the production render path (opt-in).

Set ``LCES_MC_FAULTS=1`` on Linux with the pinned toolchain. Every case
asserts the terminal state, that the old video is untouched, and that no
staging directory is left behind. Disk-full simulation is a unit case in
``test_motion_canvas.py`` plus a POSIX read-only case here.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from content_studio import motion_canvas as mc
from content_studio.errors import RenderCancelled, RenderError
from content_studio.models import VisualSpec
from content_studio.paths import ensure_project_layout
from content_studio.renderers import RenderContext

pytestmark = pytest.mark.motion

requires_faults = pytest.mark.skipif(
    os.environ.get("LCES_MC_FAULTS") != "1",
    reason="set LCES_MC_FAULTS=1 to run the fault cases",
)
POSIX = os.name == "posix"


def _spec(duration_ms: int = 10_000) -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": "title",
        "duration_ms": duration_ms,
        "data": {"title": "故障注入", "subtitle": "10 秒档"},
    }
    video = {
        "project_id": "faults",
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
        visual_id="fault-10s",
        visual_type="animation",
        renderer=mc.MotionCanvasRenderer.name,
        data={"scene_set": {"scenes": [scene]}, "video": video},
    )


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = ensure_project_layout(tmp_path / "project")
    media = project / "build" / "media"
    media.mkdir(parents=True, exist_ok=True)
    sentinel = media / "course.mp4"
    sentinel.write_bytes(b"old-video")
    return project, sentinel


def _staging(project: Path) -> list[Path]:
    return list((project / "build" / "media").glob(".staging-*"))


def _render(project: Path, renderer: mc.MotionCanvasRenderer):
    return renderer.render(
        _spec(),
        RenderContext(project_dir=project, output_dir=project / "build", publish=True),
    )


@requires_faults
def test_timeout_leaves_the_old_video_and_no_staging(tmp_path):
    project, sentinel = _project(tmp_path)
    renderer = mc.MotionCanvasRenderer(max_render_ms=1500)
    with pytest.raises(RenderError) as caught:
        _render(project, renderer)
    assert caught.value.code == "render_timeout"
    assert sentinel.read_bytes() == b"old-video"
    assert _staging(project) == []
    assert "cleaned" in " | ".join(renderer.get_diagnostics())


@requires_faults
def test_cancel_mid_render_leaves_the_old_video(tmp_path):
    project, sentinel = _project(tmp_path)
    renderer = mc.MotionCanvasRenderer(max_render_ms=60_000)
    timer = threading.Timer(2.0, renderer.cancel)
    timer.start()
    try:
        with pytest.raises(RenderCancelled):
            _render(project, renderer)
    finally:
        timer.cancel()
    assert sentinel.read_bytes() == b"old-video"
    assert _staging(project) == []
    assert "cleaned" in " | ".join(renderer.get_diagnostics())


@requires_faults
def test_cancel_during_encode_publishes_nothing(tmp_path, monkeypatch):
    project, sentinel = _project(tmp_path)
    renderer = mc.MotionCanvasRenderer(max_render_ms=60_000)
    original = mc.encode_frames

    def cancel_then_encode(*args, **kwargs):
        renderer.cancel()
        return original(*args, **kwargs)

    monkeypatch.setattr(mc, "encode_frames", cancel_then_encode)
    with pytest.raises(RenderCancelled):
        _render(project, renderer)
    assert sentinel.read_bytes() == b"old-video"
    assert _staging(project) == []


@requires_faults
def test_retry_after_timeout_publishes(tmp_path):
    project, sentinel = _project(tmp_path)
    with pytest.raises(RenderError) as caught:
        _render(project, mc.MotionCanvasRenderer(max_render_ms=1500))
    assert caught.value.code == "render_timeout"
    assert sentinel.read_bytes() == b"old-video"

    result = _render(project, mc.MotionCanvasRenderer(max_render_ms=120_000))
    assert result.status == "completed"
    assert sentinel.stat().st_size > len(b"old-video")
    assert _staging(project) == []
    qa = json.loads((project / "internal" / "qa" / "visual_qa.json").read_text(encoding="utf-8"))
    assert qa["status"] == "pass"


@requires_faults
@pytest.mark.skipif(not POSIX, reason="read-only directories need POSIX permissions")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses directory permissions",
)
def test_read_only_media_directory_is_encode_failed(tmp_path, monkeypatch):
    """A controlled filesystem failure, not a mocked exception."""

    project, sentinel = _project(tmp_path)
    media = project / "build" / "media"
    media.chmod(0o500)
    try:
        with pytest.raises(RenderError) as caught:
            _render(project, mc.MotionCanvasRenderer(max_render_ms=60_000))
    finally:
        media.chmod(0o700)
    assert caught.value.code == "encode_failed"
    assert sentinel.read_bytes() == b"old-video"
    assert _staging(project) == []
