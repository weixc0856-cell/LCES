"""P1.3: encoding is explicit, fails closed, and produces a verifiable video."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from content_studio import encode
from content_studio.encode import build_encode_command, encode_frames, encode_report
from content_studio.errors import RenderError
from content_studio.frame_manifest import build_frame_manifest
from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.timeline import plan_timeline
from content_studio.video_qa import verify_video_against_manifest


def _manifest(total: int = 3, fps_num: int = 30, fps_den: int = 1) -> FrameManifest:
    return FrameManifest(
        build_id="build-test-001",
        asset_id="course-v1",
        fps_num=fps_num,
        fps_den=fps_den,
        width=320,
        height=180,
        total_frames=total,
        scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=total)],
        frames=[
            FrameEntry(
                index=index,
                path=f"frames/project/{index:06d}.png",
                sha256="a" * 64,
                width=320,
                height=180,
            )
            for index in range(total)
        ],
    )


def test_encode_command_pins_every_parameter(tmp_path):
    command = build_encode_command(
        _manifest(), build_root=tmp_path, output=tmp_path / "course.mp4", ffmpeg_bin="ffmpeg"
    )
    joined = " ".join(command)
    assert "-framerate 30/1" in joined
    assert "-start_number 0" in joined
    assert "-frames:v 3" in joined
    assert "-pix_fmt yuv420p" in joined
    assert "-c:v libx264" in joined
    assert "-movflags +faststart" in joined
    assert command[-1] == str(tmp_path / "course.mp4")
    assert command[-2] == "+faststart"
    pattern = Path(command[command.index("-i") + 1])
    assert pattern.name == "%06d.png"
    assert pattern.parent.name == "project"


def test_encode_report_redacts_build_paths(tmp_path):
    """P2.3-E: the report is uploaded, so it must not carry runner paths."""

    video = tmp_path / "media" / "course.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    command = [
        str(tmp_path / "bin" / "ffmpeg"),
        "-i",
        str(tmp_path / "frames" / "project" / "%06d.png"),
        "-y",
        str(video),
    ]
    report = encode_report(
        _manifest(),
        output=video,
        command=command,
        manifest_sha256="f" * 64,
        path_root=tmp_path,
    )
    assert report["schema_version"] == "1.2"
    assert report["command_paths"] == "build-relative"
    assert report["command"][0] == "ffmpeg"
    assert report["command"][2] == "<build>/frames/project/%06d.png"
    assert report["command"][-1] == "<build>/media/course.mp4"
    assert str(tmp_path) not in json.dumps(report)


def test_encode_report_keeps_absolute_paths_without_build_root(tmp_path):
    video = tmp_path / "course.mp4"
    video.write_bytes(b"video")
    report = encode_report(
        _manifest(), output=video, command=["ffmpeg", str(video)], manifest_sha256="f" * 64
    )
    assert report["command_paths"] == "absolute"
    assert report["command"][1] == str(video)


def _patch_ffmpeg(monkeypatch, *, result=None, error=None):
    monkeypatch.setattr(encode, "ffmpeg_path", lambda: "ffmpeg")

    def fake_run(*args, **kwargs):
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(encode.subprocess, "run", fake_run)


def test_non_zero_exit_is_encode_failed(tmp_path, monkeypatch):
    _patch_ffmpeg(
        monkeypatch, result=subprocess.CompletedProcess([], returncode=1, stdout="", stderr="boom")
    )
    with pytest.raises(RenderError) as caught:
        encode_frames(_manifest(), build_root=tmp_path, output=tmp_path / "course.mp4")
    assert caught.value.code == "encode_failed"
    assert "boom" in str(caught.value)


def test_timeout_is_encode_failed(tmp_path, monkeypatch):
    _patch_ffmpeg(monkeypatch, error=subprocess.TimeoutExpired("ffmpeg", 1))
    with pytest.raises(RenderError) as caught:
        encode_frames(_manifest(), build_root=tmp_path, output=tmp_path / "course.mp4")
    assert caught.value.code == "encode_failed"


def test_missing_output_is_encode_failed(tmp_path, monkeypatch):
    _patch_ffmpeg(
        monkeypatch,
        result=subprocess.CompletedProcess([], returncode=0, stdout="", stderr=""),
    )
    with pytest.raises(RenderError) as caught:
        encode_frames(_manifest(), build_root=tmp_path, output=tmp_path / "course.mp4")
    assert caught.value.code == "encode_failed"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_real_encode_matches_the_manifest(tmp_path):
    plan = plan_timeline([334], fps_num=30, fps_den=1)  # 10 frames
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames" / "project"
    frames_dir.mkdir(parents=True)
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
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
        build_id="build-test-001",
        asset_id="course-v1",
        plan=plan,
        scene_ids=["scene-001"],
        frames_dir=frames_dir,
        build_root=build_root,
        width=320,
        height=180,
    )
    output = build_root / "media" / ".staging" / "course.mp4"
    encode_frames(manifest, build_root=build_root, output=output)
    assert output.is_file() and output.stat().st_size > 0
    assert verify_video_against_manifest(output, manifest) == []
