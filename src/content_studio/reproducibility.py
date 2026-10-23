"""Level 3 reproducibility measurement (P2.4-C).

Two renders of the same scene in the same environment are compared and the
result is written as evidence. The numbers are measurements, not promises:

* the byte-identical rate is recorded, never asserted as 1.0;
* visual metric deltas are recorded per sampled frame;
* the environment (versions and lockfile hash) is part of the report, because
  a rate without an environment says nothing.

Cross-OS or cross-GPU claims are out of scope; the report states what this
environment produced on this run.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import Any

from content_studio import __version__
from content_studio.media import ffmpeg_version
from content_studio.models import FrameManifest
from content_studio.motion_canvas import (
    MOTION_CANVAS_VERSION,
    NODE_VERSION,
    PLAYWRIGHT_VERSION,
    motion_project_dir,
)
from content_studio.utils import sha256_file, utc_now_iso

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class FrameComparison:
    total: int
    identical: int
    differing: list[int] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.identical / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "identical": self.identical,
            "byte_identical_rate": round(self.rate, 6),
            "differing_frames": list(self.differing),
        }


def compare_manifests(first: FrameManifest, second: FrameManifest) -> FrameComparison:
    """Compare per-frame SHA-256 values in timeline order."""

    shared = min(len(first.frames), len(second.frames))
    differing = [
        left.index
        for left, right in zip(first.frames[:shared], second.frames[:shared], strict=True)
        if left.sha256 != right.sha256
    ]
    return FrameComparison(total=shared, identical=shared - len(differing), differing=differing)


def compare_visual(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Metric deltas between two ``visual_qa.json`` payloads."""

    left = {frame["index"]: frame for frame in first.get("frames", [])}
    right = {frame["index"]: frame for frame in second.get("frames", [])}
    shared = sorted(set(left) & set(right))
    foreground = max(
        (
            abs(left[index]["foreground_ratio"] - right[index]["foreground_ratio"])
            for index in shared
        ),
        default=0.0,
    )
    edges = max(
        (abs(left[index]["edge_ratio"] - right[index]["edge_ratio"]) for index in shared),
        default=0.0,
    )
    return {
        "sampled_frames": shared,
        "max_foreground_delta": round(float(foreground), 6),
        "max_edge_delta": round(float(edges), 6),
        "status_match": first.get("status") == second.get("status"),
    }


def environment() -> dict[str, Any]:
    lockfile = motion_project_dir() / "package-lock.json"
    return {
        "lces_version": __version__,
        "python_version": platform.python_version(),
        "node_version": NODE_VERSION,
        "motion_canvas_version": MOTION_CANVAS_VERSION,
        "playwright_version": PLAYWRIGHT_VERSION,
        "ffmpeg_version": ffmpeg_version(),
        "package_lock_sha256": sha256_file(lockfile) if lockfile.is_file() else "",
    }


def build_report(
    *,
    scene: dict[str, Any],
    first: FrameManifest,
    second: FrameManifest,
    first_visual: dict[str, Any],
    second_visual: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "scene": scene,
        "builds": [first.build_id, second.build_id],
        "frames": compare_manifests(first, second).as_dict(),
        "visual": compare_visual(first_visual, second_visual),
        "environment": environment(),
        "scope": "same environment and toolchain only; no cross-OS claim",
    }
