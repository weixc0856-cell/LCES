"""MC-04 automatic visual checks for rendered frames (P2.4-A).

FrameManifest and ffprobe prove that a build produced valid PNGs and a
decodable video. They cannot tell a black rectangle from a title card. This
module samples frames from the build window, decodes them to a small
grayscale image with the system FFmpeg, and asks three questions per frame:

* how much of the frame is the background colour (mode share);
* how much differs from it (foreground ratio);
* how much structure exists (edge ratio).

Thresholds live in per-template profiles so a future template can declare
its own limits or an intentional solid card. The values are initial
calibrations, not universal production gates; false positives and negatives
are recorded during acceptance.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from content_studio.errors import RenderError
from content_studio.models import FrameManifest

SCHEMA_VERSION = "1.0"
SAMPLE_WIDTH = 160
SAMPLE_LIMIT = 9
START_SKIP_SECONDS = 1.0
END_SKIP_SECONDS = 0.5
FOREGROUND_DELTA = 24
EDGE_DELTA = 40
DECODE_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class VisualProfile:
    template: str
    min_foreground: float = 0.002
    min_edges: float = 0.001
    allow_blank: bool = False


# Per-template calibration. A solid title card can set allow_blank=True; fade
# frames are excluded by the sampling window instead of by loosening limits.
VISUAL_PROFILES: dict[str, VisualProfile] = {
    "title": VisualProfile("title"),
    "flow": VisualProfile("flow"),
    "compare": VisualProfile("compare"),
}


def profile_for(template: str) -> VisualProfile:
    return VISUAL_PROFILES.get(template, VisualProfile(template))


@dataclass(frozen=True)
class FrameMetrics:
    index: int
    background_share: float
    foreground_ratio: float
    edge_ratio: float
    blank: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "background_share": round(self.background_share, 6),
            "foreground_ratio": round(self.foreground_ratio, 6),
            "edge_ratio": round(self.edge_ratio, 6),
            "blank": self.blank,
        }


@dataclass(frozen=True)
class VisualQAReport:
    template: str
    profile: VisualProfile
    sampled: list[FrameMetrics]
    blank_frames: list[int]

    @property
    def status(self) -> str:
        return "fail" if self.blank_frames else "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "template": self.template,
            "status": self.status,
            "sampled_frames": [metrics.index for metrics in self.sampled],
            "blank_frames": self.blank_frames,
            "thresholds": {
                "min_foreground": self.profile.min_foreground,
                "min_edges": self.profile.min_edges,
                "allow_blank": self.profile.allow_blank,
                "foreground_delta": FOREGROUND_DELTA,
                "edge_delta": EDGE_DELTA,
            },
            "frames": [metrics.as_dict() for metrics in self.sampled],
        }


def sample_indices(total_frames: int, fps_num: int, fps_den: int) -> list[int]:
    """Frame indices inside the rendered window, excluding fades."""

    if total_frames <= 0:
        return []
    fps = fps_num / fps_den if fps_den else 1.0
    start = min(total_frames - 1, int(round(START_SKIP_SECONDS * fps)))
    end = max(start, total_frames - 1 - int(round(END_SKIP_SECONDS * fps)))
    if end <= start:
        return [total_frames // 2]
    count = min(SAMPLE_LIMIT, end - start + 1)
    if count == 1:
        return [start]
    step = (end - start) / (count - 1)
    return sorted({int(round(start + index * step)) for index in range(count)})


def gray_metrics(buffer: bytes, width: int, height: int) -> tuple[float, float, float]:
    """(background_share, foreground_ratio, edge_ratio) for an 8-bit gray image."""

    if len(buffer) < width * height or width < 2 or height < 2:
        raise ValueError("gray buffer is smaller than the declared image")
    total = width * height
    histogram = [0] * 256
    for value in buffer[:total]:
        histogram[value] += 1
    background = max(range(256), key=histogram.__getitem__)
    background_share = histogram[background] / total
    foreground = sum(1 for value in buffer[:total] if abs(value - background) > FOREGROUND_DELTA)
    edges = 0
    for row in range(height - 1):
        offset = row * width
        for column in range(width - 1):
            index = offset + column
            if (
                abs(buffer[index + 1] - buffer[index]) > EDGE_DELTA
                or abs(buffer[index + width] - buffer[index]) > EDGE_DELTA
            ):
                edges += 1
    return background_share, foreground / total, edges / ((width - 1) * (height - 1))


def _decode_gray(frame: Path, ffmpeg_bin: str) -> tuple[bytes, int, int]:
    command = [
        ffmpeg_bin,
        "-v",
        "error",
        "-i",
        str(frame),
        "-vf",
        f"scale={SAMPLE_WIDTH}:-1,format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=DECODE_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(
            f"cannot decode {frame.name} for visual QA: {exc.__class__.__name__}",
            code="qa_failed",
            stage="qa",
        ) from exc
    if completed.returncode != 0 or not completed.stdout:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace")[:200]
        raise RenderError(
            f"cannot decode {frame.name} for visual QA: {detail}",
            code="qa_failed",
            stage="qa",
        )
    width = SAMPLE_WIDTH
    height = len(completed.stdout) // width
    if height < 2:
        raise RenderError(
            f"visual QA decoded {frame.name} to {width}x{height}",
            code="qa_failed",
            stage="qa",
        )
    return completed.stdout[: width * height], width, height


def analyze_frames(
    manifest: FrameManifest,
    *,
    build_root: Path,
    template: str,
    ffmpeg_bin: str,
    decode: Callable[[Path], tuple[bytes, int, int]] | None = None,
) -> VisualQAReport:
    """Sample the build's frames and classify blank ones."""

    profile = profile_for(template)
    reader = decode or (lambda path: _decode_gray(path, ffmpeg_bin))
    sampled: list[FrameMetrics] = []
    blank: list[int] = []
    for index in sample_indices(manifest.total_frames, manifest.fps_num, manifest.fps_den):
        entry = manifest.frames[index]
        buffer, width, height = reader(build_root / entry.path)
        background_share, foreground_ratio, edge_ratio = gray_metrics(buffer, width, height)
        is_blank = foreground_ratio < profile.min_foreground and edge_ratio < profile.min_edges
        if profile.allow_blank:
            is_blank = False
        sampled.append(
            FrameMetrics(
                index=index,
                background_share=background_share,
                foreground_ratio=foreground_ratio,
                edge_ratio=edge_ratio,
                blank=is_blank,
            )
        )
        if is_blank:
            blank.append(index)
    return VisualQAReport(template=template, profile=profile, sampled=sampled, blank_frames=blank)
