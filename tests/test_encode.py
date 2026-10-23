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


class _FakeProcess:
    def __init__(self, *, returncode: int, stderr: str = "", hang: bool = False) -> None:
        self.pid = 4242
        self.returncode: int | None = None if hang else returncode
        self._stderr = stderr
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def communicate(self) -> tuple[str, str]:
        if self.returncode is None:
            self.returncode = -9
        return "", self._stderr

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = -9
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def _patch_ffmpeg(
    monkeypatch, *, returncode: int = 0, stderr: str = "", hang: bool = False
) -> list[_FakeProcess]:
    started: list[_FakeProcess] = []
    monkeypatch.setattr(encode, "ffmpeg_path", lambda: "ffmpeg")

    def fake_popen(command, **kwargs):
        process = _FakeProcess(returncode=returncode, stderr=stderr, hang=hang)
        started.append(process)
        return process

    monkeypatch.setattr(encode.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(encode, "_terminate", lambda process: process.terminate())
    return started


def test_non_zero_exit_is_encode_failed(tmp_path, monkeypatch):
    _patch_ffmpeg(monkeypatch, returncode=1, stderr="boom")
    with pytest.raises(RenderError) as caught:
        encode_frames(_manifest(), build_root=tmp_path, output=tmp_path / "course.mp4")
    assert caught.value.code == "encode_failed"
    assert "boom" in str(caught.value)


def test_timeout_is_encode_failed(tmp_path, monkeypatch):
    started = _patch_ffmpeg(monkeypatch, hang=True)
    with pytest.raises(RenderError) as caught:
        encode_frames(
            _manifest(), build_root=tmp_path, output=tmp_path / "course.mp4", timeout_seconds=0
        )
    assert caught.value.code == "encode_failed"
    assert started[0].terminated is True


def test_cancel_stops_the_encoder(tmp_path, monkeypatch):
    import threading

    from content_studio.errors import RenderCancelled

    started = _patch_ffmpeg(monkeypatch, hang=True)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RenderCancelled):
        encode_frames(
            _manifest(), build_root=tmp_path, output=tmp_path / "course.mp4", cancel=cancel
        )
    assert started[0].terminated is True


def test_missing_output_is_encode_failed(tmp_path, monkeypatch):
    _patch_ffmpeg(monkeypatch)
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
