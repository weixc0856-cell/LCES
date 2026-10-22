"""P1.3: Gate 4 re-checks a real encoded video against the real manifest."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from content_studio.encode import encode_frames
from content_studio.frame_manifest import build_frame_manifest
from content_studio.timeline import plan_timeline
from content_studio.utils import sha256_file, write_json
from content_studio.validation import run_release_checks

pytestmark = pytest.mark.motion

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@pytest.fixture
def media_setup(tmp_path):
    if FFMPEG is None or FFPROBE is None:
        pytest.skip("FFmpeg and ffprobe are required")
    release = tmp_path / "release"
    (release / "media").mkdir(parents=True)
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames" / "project"
    frames_dir.mkdir(parents=True)
    plan = plan_timeline([334], fps_num=30, fps_den=1)  # 10 frames
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=30:d=1",
            "-frames:v",
            str(plan.total_frames),
            "-start_number",
            "0",
            str(frames_dir / "%06d.png"),
        ],
        check=True,
    )
    manifest = build_frame_manifest(
        build_id="build-gate-real",
        asset_id="course-v1",
        plan=plan,
        scene_ids=["scene-001"],
        frames_dir=frames_dir,
        build_root=build_root,
        width=320,
        height=180,
    )
    video = release / "media" / "course.mp4"
    encode_frames(manifest, build_root=build_root, output=video)
    write_json(project / "internal" / "qa" / "frame_manifest.json", manifest)
    write_json(
        project / "internal" / "qa" / "encode_report.json",
        {"video_sha256": sha256_file(video)},
    )
    return release, project, video


def _gate_checks(release: Path, project: Path):
    return run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=False,
        project_dir=project,
    )


def test_gate4_accepts_a_real_video(media_setup):
    release, project, _video = media_setup
    statuses = {item.check_id: item.status for item in _gate_checks(release, project)}
    assert statuses["video_matches_manifest"] == "pass"
    assert statuses["video_hash_matches_encode_report"] == "pass"


def test_gate4_rejects_a_short_video(media_setup):
    release, project, video = media_setup
    frames_dir = project.parent / "build" / "frames" / "project"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-framerate",
            "30/1",
            "-start_number",
            "0",
            "-i",
            str(frames_dir / "%06d.png"),
            "-frames:v",
            "9",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    statuses = {item.check_id: item.status for item in _gate_checks(release, project)}
    assert statuses["video_matches_manifest"] == "fail"
    assert statuses["video_hash_matches_encode_report"] == "fail"
