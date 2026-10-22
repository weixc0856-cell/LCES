"""Compare an encoded video with the FrameManifest that produced it (P1.3).

The container's single ``duration`` field is not enough: a truncated encode can
still carry a plausible duration. This module checks the decoded frame count,
the rational frame rate, the dimensions, the duration within one frame, and a
full decode pass.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from content_studio.errors import MediaError
from content_studio.media import ffmpeg_path, ffprobe_path
from content_studio.models import FrameManifest


@dataclass(frozen=True)
class VideoInfo:
    frames: int
    width: int
    height: int
    fps: Fraction
    duration: Fraction


def parse_probe(payload: dict) -> VideoInfo:
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise MediaError("ffprobe returned no video stream")
    stream = streams[0]
    frames = int(stream.get("nb_read_frames") or 0)
    if frames <= 0:
        raise MediaError("ffprobe decoded no frames; use -count_frames")
    fps = Fraction(str(stream.get("avg_frame_rate") or "0/0"))
    if fps == 0:
        fps = Fraction(str(stream.get("r_frame_rate") or "0/0"))
    if fps <= 0:
        raise MediaError("ffprobe reported an invalid frame rate")
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise MediaError("ffprobe reported invalid dimensions")
    raw_duration = payload.get("format", {}).get("duration") or stream.get("duration")
    try:
        duration = Fraction(str(raw_duration))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise MediaError("ffprobe reported an invalid duration") from exc
    return VideoInfo(frames=frames, width=width, height=height, fps=fps, duration=duration)


def probe_video(path: Path, *, ffprobe: str | None = None) -> VideoInfo:
    binary = ffprobe or ffprobe_path()
    if binary is None:
        raise MediaError("ffprobe is not installed")
    if not path.is_file():
        raise MediaError(f"video not found: {path.name}")
    command = [
        binary,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_read_frames,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"ffprobe could not run: {exc.__class__.__name__}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        raise MediaError(detail[-1][:300] if detail else "ffprobe failed")
    try:
        payload = json.loads(completed.stdout)
    except ValueError as exc:
        raise MediaError("ffprobe returned unreadable JSON") from exc
    return parse_probe(payload)


def decode_video(path: Path, *, ffmpeg: str | None = None) -> str:
    """Return a problem message, or ``""`` when the whole file decodes."""

    binary = ffmpeg or ffmpeg_path()
    if binary is None:
        return "ffmpeg is not installed, so the video cannot be decoded"
    try:
        completed = subprocess.run(
            [binary, "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ffmpeg decode could not run: {exc.__class__.__name__}"
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        return f"video cannot be decoded: {message[:300]}"
    return ""


def verify_video_against_manifest(
    video: Path, manifest: FrameManifest, *, tolerance_frames: int = 1
) -> list[str]:
    """Problems that make the video unpublishable; empty means consistent."""

    try:
        info = probe_video(video)
    except MediaError as exc:
        return [str(exc)]
    problems: list[str] = []
    if info.frames != manifest.total_frames:
        problems.append(f"video decodes {info.frames} frames, manifest has {manifest.total_frames}")
    expected_fps = Fraction(manifest.fps_num, manifest.fps_den)
    if info.fps != expected_fps:
        problems.append(f"video fps {info.fps} does not match {expected_fps}")
    if (info.width, info.height) != (manifest.width, manifest.height):
        problems.append(
            f"video is {info.width}x{info.height}, expected {manifest.width}x{manifest.height}"
        )
    expected_duration = Fraction(manifest.total_frames * manifest.fps_den, manifest.fps_num)
    frame = Fraction(manifest.fps_den, manifest.fps_num)
    delta = abs(info.duration - expected_duration)
    if delta > frame * tolerance_frames:
        problems.append(
            f"video duration {float(info.duration):.6f}s differs from "
            f"{float(expected_duration):.6f}s by more than {tolerance_frames} frame(s)"
        )
    decode = decode_video(video)
    if decode:
        problems.append(decode)
    return problems
