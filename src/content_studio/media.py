"""Media probing, frame sampling, and subtitle timing checks (Phase 5).

FFmpeg and ffprobe are external tools, not Python dependencies. When they are
missing the caller must report NOT_RUN; when they fail on a file the caller
must report FAIL. Nothing here guesses a duration or hides a decode error.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from content_studio.errors import MediaError

TIMESTAMP = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})\s*-->\s*"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2})[,.](?P<ms2>\d{3})"
)


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    size_bytes: int

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)

    def summary(self) -> str:
        audio = f"audio={self.audio_codec}" if self.has_audio else "no audio"
        return (
            f"{self.width}x{self.height}, {self.duration_seconds:.2f}s, "
            f"video={self.video_codec}, {audio}, {self.size_bytes} bytes"
        )


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffmpeg_version() -> str:
    """Version string of the system FFmpeg, or ``""`` when unavailable."""

    binary = ffmpeg_path()
    if binary is None:
        return ""
    try:
        completed = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = completed.stdout or completed.stderr or ""
    match = re.search(r"ffmpeg version (\d+\.\d+(?:\.\d+)?)", output)
    return match.group(1) if match else ""


def tool_status() -> tuple[bool, str]:
    tools = {"ffprobe": ffprobe_path(), "ffmpeg": ffmpeg_path()}
    missing = [name for name, found in tools.items() if not found]
    if missing:
        return False, f"缺少 {', '.join(missing)}；安装 FFmpeg 后重试"
    return True, ""


def probe_media(path: Path) -> MediaInfo:
    """Read stream metadata; raises :class:`MediaError` if the file is unusable."""

    binary = ffprobe_path()
    if binary is None:
        raise MediaError("ffprobe is not installed; install FFmpeg and retry")
    if not path.is_file():
        raise MediaError(f"media file not found: {path}")

    completed = _run(
        [binary, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    try:
        payload = json.loads(completed.stdout)
    except ValueError as exc:
        raise MediaError(f"ffprobe returned unreadable JSON for {path.name}") from exc

    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise MediaError(f"no decodable streams in {path.name}")
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError(f"no video stream in {path.name}")

    duration_raw = payload.get("format", {}).get("duration")
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError) as exc:
        raise MediaError(f"duration is missing or invalid in {path.name}") from exc
    if duration <= 0:
        raise MediaError(f"duration is not positive in {path.name}")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise MediaError(f"video dimensions are invalid in {path.name}")

    return MediaInfo(
        path=str(path),
        duration_seconds=duration,
        width=width,
        height=height,
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str(audio.get("codec_name") or "") if audio else "",
        size_bytes=path.stat().st_size,
    )


def extract_frames(path: Path, out_dir: Path, count: int = 4) -> list[Path]:
    """Sample ``count`` frames spread across the file for human review."""

    if count < 1:
        raise MediaError("frame count must be at least 1")
    binary = ffmpeg_path()
    if binary is None:
        raise MediaError("ffmpeg is not installed; install FFmpeg and retry")
    info = probe_media(path)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames: list[Path] = []
    for index in range(count):
        timestamp = info.duration_seconds * (index + 1) / (count + 1)
        target = out_dir / f"{path.stem}-{index + 1:02d}.jpg"
        _run(
            [
                binary,
                "-v",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(target),
            ]
        )
        if not target.is_file() or target.stat().st_size == 0:
            raise MediaError(f"frame extraction produced no image at {timestamp:.2f}s")
        frames.append(target)
    return frames


def subtitle_problems(path: Path, duration_seconds: float | None = None) -> list[str]:
    """Structural timing checks for SRT/VTT; returns human-readable problems."""

    if not path.is_file():
        return [f"字幕文件不存在: {path.name}"]
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    cues: list[tuple[float, float]] = []
    for match in TIMESTAMP.finditer(text):
        start = _seconds(match, "")
        end = _seconds(match, "2")
        cues.append((start, end))

    if not cues:
        return [f"{path.name}: 未找到合法的字幕时间轴"]

    problems: list[str] = []
    for index, (start, end) in enumerate(cues, start=1):
        if end <= start:
            problems.append(f"{path.name}: 第 {index} 条字幕结束时间不晚于开始时间")
        if duration_seconds is not None and end > duration_seconds + 0.5:
            problems.append(f"{path.name}: 第 {index} 条字幕超出视频时长")
    for index in range(1, len(cues)):
        if cues[index][0] < cues[index - 1][0]:
            problems.append(f"{path.name}: 第 {index + 1} 条字幕时间早于上一条")
    return problems


def media_problems(path: Path, *, require_audio: bool = False) -> list[str]:
    """Full check used by Gate 4 and the CLI; empty list means usable."""

    try:
        info = probe_media(path)
    except MediaError as exc:
        return [str(exc)]
    problems: list[str] = []
    if require_audio and not info.has_audio:
        problems.append(f"{path.name}: 缺少音频流")
    return problems


def _seconds(match: re.Match[str], suffix: str) -> float:
    hours = int(match.group(f"h{suffix}"))
    minutes = int(match.group(f"m{suffix}"))
    seconds = int(match.group(f"s{suffix}"))
    millis = int(match.group(f"ms{suffix}"))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MediaError(f"could not run {Path(command[0]).name}: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        raise MediaError(f"{Path(command[0]).name} failed: {message[:300]}")
    return completed
