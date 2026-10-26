import shutil
import subprocess
from pathlib import Path

import pytest

from content_studio.errors import MediaError
from content_studio.media import (
    extract_frames,
    media_problems,
    probe_duration,
    probe_media,
    subtitle_problems,
    tool_status,
)
from content_studio.validation import _media_checks

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")

VALID_SRT = """1
00:00:00,000 --> 00:00:01,000
第一句

2
00:00:01,200 --> 00:00:02,500
第二句
"""

SHORT_SRT = """1
00:00:00,000 --> 00:00:00,400
第一句

2
00:00:00,500 --> 00:00:00,900
第二句
"""


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    assert FFMPEG is not None
    path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def test_tool_status_reports_missing_tools(monkeypatch):
    monkeypatch.setattr("content_studio.media.ffprobe_path", lambda: None)
    available, reason = tool_status()
    assert available is False
    assert "ffprobe" in reason


@needs_ffmpeg
def test_probe_media_reads_stream_properties(sample_video):
    info = probe_media(sample_video)
    assert 0.5 < info.duration_seconds < 2.0
    assert (info.width, info.height) == (320, 240)
    assert info.video_codec
    assert info.has_audio
    assert "320x240" in info.summary()


@needs_ffmpeg
def test_extract_frames_writes_images(sample_video, tmp_path):
    frames = extract_frames(sample_video, tmp_path / "frames", count=2)
    assert len(frames) == 2
    assert all(frame.is_file() and frame.stat().st_size > 0 for frame in frames)


@needs_ffmpeg
def test_corrupt_media_is_an_error(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(MediaError):
        probe_media(broken)


@needs_ffmpeg
def test_media_problems_reports_decode_failure(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    problems = media_problems(broken)
    assert problems and "broken.mp4" in problems[0]


def test_subtitle_timing_accepts_valid_srt(tmp_path):
    path = tmp_path / "course.srt"
    path.write_text(VALID_SRT, encoding="utf-8")
    assert subtitle_problems(path, duration_seconds=3.0) == []


def test_subtitle_timing_rejects_bad_cues(tmp_path):
    path = tmp_path / "course.srt"
    path.write_text(
        "1\n00:00:02,000 --> 00:00:01,000\n倒序\n\n2\n00:00:04,000 --> 00:00:09,000\n超长\n",
        encoding="utf-8",
    )
    problems = subtitle_problems(path, duration_seconds=5.0)
    assert any("结束时间不晚于开始时间" in item for item in problems)
    assert any("超出视频时长" in item for item in problems)


def test_subtitle_timing_supports_webvtt(tmp_path):
    path = tmp_path / "course.vtt"
    path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello\n", encoding="utf-8")
    assert subtitle_problems(path, duration_seconds=2.0) == []


def test_missing_subtitle_file_is_reported(tmp_path):
    problems = subtitle_problems(tmp_path / "nope.srt")
    assert problems and "不存在" in problems[0]


def test_gate4_reports_not_run_without_media(tmp_path):
    checks = _media_checks(tmp_path)
    assert [check.status for check in checks] == ["not_run"]
    assert checks[0].blocking is False


@needs_ffmpeg
def test_gate4_checks_a_released_video_and_subtitles(sample_video, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    shutil.copyfile(sample_video, media / "course.mp4")
    (media / "course.srt").write_text(SHORT_SRT, encoding="utf-8")

    checks = {check.check_id: check for check in _media_checks(tmp_path)}
    assert checks["media_decodable"].status == "pass"
    assert checks["media_audio_present"].status == "pass"
    assert checks["subtitle_timing"].status == "pass"


@needs_ffmpeg
def test_gate4_fails_a_corrupt_video(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "course.mp4").write_bytes(b"broken")

    checks = {check.check_id: check for check in _media_checks(tmp_path)}
    assert checks["media_decodable"].status == "fail"
    assert checks["media_decodable"].blocking is True


@needs_ffmpeg
def test_probe_duration_reads_audio_only_media(tmp_path: Path):
    audio = tmp_path / "tone.m4a"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.5",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )

    assert probe_duration(audio) == pytest.approx(1.5, abs=0.2)


def test_probe_duration_rejects_missing_files(tmp_path: Path):
    with pytest.raises(MediaError, match="not found"):
        probe_duration(tmp_path / "absent.m4a")
