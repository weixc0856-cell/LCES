"""P1.3: the encoded video must agree with the frame manifest."""

from __future__ import annotations

from fractions import Fraction

import pytest

from content_studio import video_qa
from content_studio.errors import MediaError
from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.video_qa import VideoInfo, parse_probe, verify_video_against_manifest


def _manifest(total: int = 300, fps_num: int = 30, fps_den: int = 1) -> FrameManifest:
    return FrameManifest(
        build_id="build-test-001",
        asset_id="course-v1",
        fps_num=fps_num,
        fps_den=fps_den,
        width=1920,
        height=1080,
        total_frames=total,
        scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=total)],
        frames=[
            FrameEntry(
                index=index,
                path=f"frames/project/{index:06d}.png",
                sha256="a" * 64,
                width=1920,
                height=1080,
            )
            for index in range(total)
        ],
    )


def _info(frames=300, duration=Fraction(10), fps=Fraction(30)) -> VideoInfo:
    return VideoInfo(frames=frames, width=1920, height=1080, fps=fps, duration=duration)


def _probe(monkeypatch, info: VideoInfo) -> None:
    monkeypatch.setattr(video_qa, "probe_video", lambda path: info)
    monkeypatch.setattr(video_qa, "decode_video", lambda path: "")


def test_parse_probe_reads_decoded_frames_and_rational_rate():
    info = parse_probe(
        {
            "streams": [
                {
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "nb_read_frames": "300",
                    "duration": "10.010000",
                }
            ],
            "format": {"duration": "10.010000"},
        }
    )
    assert info.frames == 300
    assert info.fps == Fraction(30000, 1001)
    assert info.duration == Fraction("10.010000")
    assert (info.width, info.height) == (1920, 1080)


def test_parse_probe_requires_decoded_frames():
    with pytest.raises(MediaError, match="no frames"):
        parse_probe({"streams": [{"width": 1, "height": 1}]})


def test_matching_video_has_no_problems(tmp_path, monkeypatch):
    _probe(monkeypatch, _info())
    assert verify_video_against_manifest(tmp_path / "course.mp4", _manifest()) == []


def test_duration_tolerance_is_one_frame(tmp_path, monkeypatch):
    manifest = _manifest()
    _probe(monkeypatch, _info(duration=Fraction(10) + Fraction(1, 30)))
    assert verify_video_against_manifest(tmp_path / "course.mp4", manifest) == []

    _probe(monkeypatch, _info(duration=Fraction(10) + Fraction(1, 30) + Fraction(1, 1000)))
    problems = verify_video_against_manifest(tmp_path / "course.mp4", manifest)
    assert any("duration" in problem for problem in problems)


def test_frame_count_mismatch_is_reported(tmp_path, monkeypatch):
    _probe(monkeypatch, _info(frames=299))
    problems = verify_video_against_manifest(tmp_path / "course.mp4", _manifest())
    assert any("video decodes 299 frames" in problem for problem in problems)


def test_frame_rate_mismatch_is_reported(tmp_path, monkeypatch):
    _probe(monkeypatch, _info(fps=Fraction(25)))
    problems = verify_video_against_manifest(tmp_path / "course.mp4", _manifest())
    assert any("fps" in problem for problem in problems)


def test_dimension_mismatch_is_reported(tmp_path, monkeypatch):
    info = VideoInfo(frames=300, width=1280, height=720, fps=Fraction(30), duration=Fraction(10))
    _probe(monkeypatch, info)
    problems = verify_video_against_manifest(tmp_path / "course.mp4", _manifest())
    assert any("1280x720" in problem for problem in problems)


def test_decode_failure_is_reported(tmp_path, monkeypatch):
    _probe(monkeypatch, _info())
    monkeypatch.setattr(video_qa, "decode_video", lambda path: "video cannot be decoded: boom")
    problems = verify_video_against_manifest(tmp_path / "course.mp4", _manifest())
    assert any("cannot be decoded" in problem for problem in problems)


def test_ntsc_rational_is_compared_exactly(tmp_path, monkeypatch):
    manifest = _manifest(total=300, fps_num=30000, fps_den=1001)
    _probe(
        monkeypatch,
        VideoInfo(
            frames=300,
            width=1920,
            height=1080,
            fps=Fraction(30000, 1001),
            duration=Fraction(300 * 1001, 30000),
        ),
    )
    assert verify_video_against_manifest(tmp_path / "course.mp4", manifest) == []
