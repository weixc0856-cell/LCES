"""P1 end-to-end renders: real editor, real Chromium, real frames.

Skipped by default because P1 is Linux-only. The CI job ``motion-canvas-p1``
sets ``LCES_MC_E2E=1`` and must fail, not skip, when the pinned toolchain is
missing -- a skipped integration test cannot discharge the gate.

Two configurations run in CI:

* smoke: 640x360, 30 frames -- the fast per-PR check;
* production: 1920x1080, 300 frames (10 s at 30 fps) -- the P1 acceptance
  configuration. The smoke run does not stand in for it.

P1.4 adds two negative end-to-end cases (cancel after the first frame, and an
adapter-enforced timeout). Both must leave an older ``course.mp4`` untouched.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

import pytest

from content_studio import motion_canvas as mc
from content_studio.errors import RenderCancelled, RenderError
from content_studio.frame_manifest import png_problems
from content_studio.models import FrameManifest, VisualSpec
from content_studio.renderers import RenderContext
from content_studio.utils import sha256_file
from content_studio.video_qa import verify_video_against_manifest

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


@contextlib.contextmanager
def host_home_canary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point HOME at a canary while keeping Playwright's browser lookup.

    The driver's HOME is isolated to the build, so Playwright resolves its
    registry from the build directory. Resolve the host directory *before*
    HOME moves and pin it for this test only; an explicit
    ``PLAYWRIGHT_BROWSERS_PATH`` (including ``0``) is never overridden.
    """

    host_home = tmp_path / "host-home"
    host_home.mkdir(exist_ok=True)
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip():
        resolved = mc.playwright_browsers_path()
        if resolved is None:
            pytest.fail(
                "cannot resolve the host Playwright browser directory; "
                "set PLAYWRIGHT_BROWSERS_PATH so the isolated HOME can still find Chromium"
            )
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", resolved)
    monkeypatch.setenv("HOME", str(host_home))
    yield host_home


def _render(
    tmp_path: Path, spec: VisualSpec, *, max_render_ms: int, monkeypatch: pytest.MonkeyPatch
) -> dict:
    if os.environ.get("LCES_MC_E2E") != "1":
        pytest.skip("set LCES_MC_E2E=1 on a Linux host with the pinned toolchain")

    renderer = mc.MotionCanvasRenderer(max_render_ms=max_render_ms)
    problems = renderer.check_environment()
    assert not problems, (
        "P1 E2E needs the pinned toolchain (a missing dependency is a failure, "
        "not a skip): " + "; ".join(problems)
    )

    # N09: point the host HOME at a canary. The driver must use the build's
    # own HOME/TMP, so a successful render leaves the canary untouched.
    with host_home_canary(tmp_path, monkeypatch) as host_home:
        result = renderer.render(
            spec,
            RenderContext(output_dir=tmp_path, project_dir=tmp_path / "project", publish=True),
        )
    assert result.status == "completed"
    assert result.build_id
    assert not list(host_home.iterdir()), "the render wrote into the host HOME"
    build_homes = list((tmp_path / "project" / "build" / "motion").glob("*/home"))
    assert len(build_homes) == 1, "the driver HOME must live inside the build directory"
    assert build_homes[0].is_dir()

    report_path = next(path for path in result.artifacts if path.name == "report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["finished"] is True
    assert report["terminal"] == "completed"
    assert report["error_code"] == ""
    # Offline isolation is an OS-level claim proved in P1.4; P1.1 only records
    # what the driver observed. P0 saw failed external attempts even with no
    # network, so an empty list is not a valid assertion here.
    assert isinstance(report["external_requests"], list)
    if os.environ.get("LCES_MC_OFFLINE") == "1":
        assert report["external_requests"], (
            "the offline run attempted no external request, so it does not "
            "demonstrate that external requests were blocked"
        )
        assert report["request_failures"] > 0, (
            "external requests were not blocked; the container was not offline"
        )

    video = tmp_path / "project" / "build" / "media" / "course.mp4"
    assert video.is_file(), "the adapter must publish an encoded video"
    manifest_path = next(tmp_path.rglob("frame_manifest.json"))
    manifest = FrameManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert verify_video_against_manifest(video, manifest) == []

    # P1.3 evidence: the encode report is written for Gate 4 and must describe
    # the exact video on disk, not a stale staging file.
    qa_dir = tmp_path / "project" / "internal" / "qa"
    encode_report = json.loads((qa_dir / "encode_report.json").read_text(encoding="utf-8"))
    assert encode_report["build_id"] == result.build_id
    assert encode_report["frames"] == manifest.total_frames
    assert encode_report["video_sha256"] == sha256_file(video)
    assert encode_report["command"], "the FFmpeg argv must be recorded"
    assert (qa_dir / "frame_manifest.json").is_file()
    diagnostics = " | ".join(renderer.get_diagnostics())
    assert "process group" in diagnostics and "cleaned" in diagnostics
    return report


def test_smoke_config_renders_30_frames(tmp_path, monkeypatch):
    report = _render(
        tmp_path,
        _spec(duration_ms=1000, width=640, height=360),
        max_render_ms=180_000,
        monkeypatch=monkeypatch,
    )
    assert report["frames"] == 30


def test_production_config_renders_300_frames_at_1080p(tmp_path, monkeypatch):
    report = _render(
        tmp_path,
        _spec(duration_ms=10_000, width=1920, height=1080),
        max_render_ms=300_000,
        monkeypatch=monkeypatch,
    )
    assert report["frames"] == 300
    frames = sorted(tmp_path.rglob("000000.png"))[0].parent
    assert png_problems(frames / "000000.png", 1920, 1080) == []
    assert png_problems(frames / "000299.png", 1920, 1080) == []


# -- P1.4: cancellation and timeout end to end ---------------------------


def _ready_renderer(*, max_render_ms: int) -> mc.MotionCanvasRenderer:
    if os.environ.get("LCES_MC_E2E") != "1":
        pytest.skip("set LCES_MC_E2E=1 on a Linux host with the pinned toolchain")
    renderer = mc.MotionCanvasRenderer(max_render_ms=max_render_ms)
    problems = renderer.check_environment()
    assert not problems, (
        "P1 E2E needs the pinned toolchain (a missing dependency is a failure, "
        "not a skip): " + "; ".join(problems)
    )
    return renderer


def _has_frame(root: Path) -> bool:
    return any(path.suffix == ".png" and path.stem.isdigit() for path in root.rglob("*.png"))


def test_cancel_mid_render_publishes_nothing(tmp_path):
    """The whole process group stops, and no publishable evidence is left."""

    renderer = _ready_renderer(max_render_ms=300_000)
    media = tmp_path / "project" / "build" / "media"
    media.mkdir(parents=True)
    sentinel = media / "course.mp4"
    sentinel.write_bytes(b"old-video")

    spec = _spec(duration_ms=10_000, width=1920, height=1080)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            renderer.render(
                spec,
                RenderContext(output_dir=tmp_path, project_dir=tmp_path / "project", publish=True),
            )
        except BaseException as exc:  # asserted below
            errors.append(exc)

    thread = threading.Thread(target=run, name="motion-cancel-test")
    thread.start()
    deadline = time.monotonic() + 120
    saw_frame = False
    while time.monotonic() < deadline:
        if _has_frame(tmp_path):
            saw_frame = True
            break
        if not thread.is_alive():
            break
        time.sleep(0.05)

    renderer.cancel()
    thread.join(timeout=120)
    assert not thread.is_alive(), "cancel did not stop the render"
    assert saw_frame, "the build ended before a frame existed; cancellation was not exercised"
    assert errors, "cancelling a live build must raise"
    assert isinstance(errors[0], RenderCancelled)
    assert errors[0].terminal == "cancelled"
    assert sentinel.read_bytes() == b"old-video"
    assert not list(tmp_path.rglob("frame_manifest.json"))
    assert sorted(path.name for path in media.glob("*.mp4")) == ["course.mp4"]
    diagnostics = " | ".join(renderer.get_diagnostics())
    assert "process group" in diagnostics and "cleaned" in diagnostics


def test_timeout_stops_the_driver_and_publishes_nothing(tmp_path):
    """The adapter, not the driver, enforces the deadline."""

    renderer = _ready_renderer(max_render_ms=1_500)
    media = tmp_path / "project" / "build" / "media"
    media.mkdir(parents=True)
    sentinel = media / "course.mp4"
    sentinel.write_bytes(b"old-video")

    spec = _spec(duration_ms=10_000, width=1920, height=1080)
    with pytest.raises(RenderError) as caught:
        renderer.render(
            spec, RenderContext(output_dir=tmp_path, project_dir=tmp_path / "project", publish=True)
        )

    assert caught.value.code == "render_timeout"
    assert caught.value.terminal == "failed"
    assert sentinel.read_bytes() == b"old-video"
    assert not list(tmp_path.rglob("frame_manifest.json"))
    assert sorted(path.name for path in media.glob("*.mp4")) == ["course.mp4"]
    diagnostics = " | ".join(renderer.get_diagnostics())
    assert "process group" in diagnostics and "cleaned" in diagnostics
