"""P3-B: duration tiers and resource baseline (opt-in).

Set ``LCES_MC_STRESS=1`` on Linux with the pinned toolchain. Tiers default to
1 s / 10 s / 60 s; the 10 s and 60 s tiers repeat to expose run-to-run noise.
The report separates timing, process-tree resources, disk and artifacts, and
records the measurement method. No threshold is asserted: this batch builds
the baseline that a later quota decision must cite.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
from pathlib import Path
from unittest import mock

import pytest

from content_studio import motion_canvas as mc
from content_studio.media import ffmpeg_version
from content_studio.models import FrameManifest, VisualSpec
from content_studio.paths import ensure_project_layout
from content_studio.renderers import RenderContext
from content_studio.resource_probe import ResourceProbe, dir_bytes
from content_studio.utils import sha256_bytes, sha256_file
from content_studio.video_qa import verify_video_against_manifest

pytestmark = pytest.mark.motion

TIERS = [
    int(value)
    for value in os.environ.get("LCES_MC_STRESS_TIERS", "1000,10000,60000").split(",")
    if value.strip()
]
REPEATS = int(os.environ.get("LCES_MC_STRESS_REPEAT", "2"))
FPS = 30

requires_stress = pytest.mark.skipif(
    os.environ.get("LCES_MC_STRESS") != "1",
    reason="set LCES_MC_STRESS=1 to run the duration tiers",
)


def _spec(duration_ms: int) -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": "title",
        "duration_ms": duration_ms,
        "data": {"title": "生产资源基线", "subtitle": f"{duration_ms // 1000} 秒档位"},
    }
    video = {
        "project_id": "stress",
        "video_id": "course-v1",
        "content_version": "v1",
        "width": 1920,
        "height": 1080,
        "fps_num": FPS,
        "fps_den": 1,
        "scene_ids": ["scene-001"],
        "output_path": "build/media/course.mp4",
        "renderer": mc.MotionCanvasRenderer.name,
        "renderer_version": mc.MotionCanvasRenderer.version,
    }
    return VisualSpec(
        visual_id=f"stress-{duration_ms}",
        visual_type="animation",
        renderer=mc.MotionCanvasRenderer.name,
        data={"scene_set": {"scenes": [scene]}, "video": video},
    )


def _timed_encoder(original, seconds: list[float]):
    def timed(*args, **kwargs):
        started = time.monotonic()
        try:
            return original(*args, **kwargs)
        finally:
            seconds.append(time.monotonic() - started)

    return timed


def _environment(spec: VisualSpec) -> dict:
    lockfile = mc.motion_project_dir() / "package-lock.json"
    return {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "node_version": mc.NODE_VERSION,
        "motion_canvas_version": mc.MOTION_CANVAS_VERSION,
        "playwright_version": mc.PLAYWRIGHT_VERSION,
        "ffmpeg_version": ffmpeg_version(),
        "package_lock_sha256": sha256_file(lockfile) if lockfile.is_file() else "",
        "spec_sha256": sha256_bytes(
            json.dumps(spec.data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ),
    }


@requires_stress
def test_duration_tiers(tmp_path):
    results: list[dict] = []
    for duration in TIERS:
        repeats = 1 if duration <= 1000 else max(1, REPEATS)
        for repeat in range(repeats):
            project = ensure_project_layout(tmp_path / f"d{duration}-r{repeat}")
            spec = _spec(duration)
            free_before = shutil.disk_usage(project).free
            encode_seconds: list[float] = []
            renderer = mc.MotionCanvasRenderer(max_render_ms=900_000)
            with (
                mock.patch.object(
                    mc, "encode_frames", _timed_encoder(mc.encode_frames, encode_seconds)
                ),
                ResourceProbe(project, interval_s=0.5) as probe,
            ):
                started = time.monotonic()
                result = renderer.render(
                    spec,
                    RenderContext(project_dir=project, output_dir=project / "build", publish=True),
                )
                total_s = time.monotonic() - started
            free_after = shutil.disk_usage(project).free

            assert result.status == "completed", f"{duration} ms"
            build = project / "build" / "motion" / result.build_id
            manifest = FrameManifest.model_validate_json(
                (build / "frame_manifest.json").read_text(encoding="utf-8")
            )
            video = project / "build" / "media" / "course.mp4"
            gate_started = time.monotonic()
            decode_problems = verify_video_against_manifest(video, manifest)
            gate4_s = time.monotonic() - gate_started
            driver = json.loads((build / "frames" / "report.json").read_text(encoding="utf-8"))

            expected = duration * FPS // 1000
            assert manifest.total_frames == expected, f"{duration} ms"
            assert (manifest.width, manifest.height) == (1920, 1080)
            assert decode_problems == [], f"{duration} ms: {decode_problems[:3]}"
            assert video.is_file() and video.stat().st_size > 0

            results.append(
                {
                    "duration_ms": duration,
                    "repeat": repeat,
                    "timing": {
                        "total_s": round(total_s, 2),
                        "render_s": driver.get("elapsed_s"),
                        "encode_s": round(sum(encode_seconds), 2),
                        "gate4_s": round(gate4_s, 2),
                    },
                    "resources": probe.report(),
                    "disk": {
                        "peak_disk_bytes": probe.report()["peak_disk_bytes"],
                        "frames_dir_bytes": dir_bytes(build / "frames"),
                        "video_bytes": video.stat().st_size,
                        "free_before": free_before,
                        "free_after": free_after,
                    },
                    "artifacts": {
                        "frames": manifest.total_frames,
                        "width": manifest.width,
                        "height": manifest.height,
                        "fps_num": manifest.fps_num,
                        "fps_den": manifest.fps_den,
                        "decode_problems": decode_problems,
                        "video_sha256": sha256_file(video),
                    },
                    "environment": _environment(spec),
                }
            )

    output = Path(os.environ.get("LCES_STRESS_OUT", str(tmp_path / "stress.json")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"tiers": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    assert len(results) == sum(1 if tier <= 1000 else max(1, REPEATS) for tier in TIERS)
    print(json.dumps({"tiers": results}, indent=2, ensure_ascii=False))
