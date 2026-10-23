"""Per-template visual baselines (P2.4-B).

A baseline is the sampled-metric record of one accepted render for a template
at a given canvas size and frame rate. Later builds compare their samples
against it and report drift; drift is a **warning**, never a silent failure,
because the automatic metrics cannot decide whether a change is intended.

Baselines live under the project's ``internal/qa/visual_baselines/`` and hold
metrics plus frame hashes, not pixels: evidence stays small and reviewable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_studio.utils import utc_now_iso, write_json

SCHEMA_VERSION = "1.0"
BASELINE_DIR = Path("internal") / "qa" / "visual_baselines"
FOREGROUND_DRIFT = 0.01
EDGE_DRIFT = 0.01


def baseline_path(
    project_dir: Path, template: str, width: int, height: int, fps_num: int, fps_den: int
) -> Path:
    return project_dir / BASELINE_DIR / f"{template}-{width}x{height}-{fps_num}_{fps_den}.json"


@dataclass(frozen=True)
class BaselineComparison:
    status: str
    path: str = ""
    warnings: list[str] = field(default_factory=list)
    byte_identical: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": self.path,
            "warnings": list(self.warnings),
            "byte_identical": self.byte_identical,
        }


def build_baseline(
    project_dir: Path,
    *,
    template: str,
    width: int,
    height: int,
    fps_num: int,
    fps_den: int,
    visual: dict[str, Any],
    build_id: str,
    note: str = "",
    frame_sha256: dict[int, str] | None = None,
) -> Path:
    """Write the baseline from a passing ``visual_qa.json`` payload."""

    if visual.get("status") != "pass":
        raise ValueError("only a passing visual report can become a baseline")
    hashes = frame_sha256 or {}
    frames = [
        {
            "index": frame["index"],
            "foreground_ratio": frame["foreground_ratio"],
            "edge_ratio": frame["edge_ratio"],
            "sha256": hashes.get(frame["index"], ""),
        }
        for frame in visual.get("frames", [])
    ]
    path = baseline_path(project_dir, template, width, height, fps_num, fps_den)
    write_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "template": template,
            "width": width,
            "height": height,
            "fps_num": fps_num,
            "fps_den": fps_den,
            "sampled_frames": list(visual.get("sampled_frames", [])),
            "thresholds": visual.get("thresholds", {}),
            "frames": frames,
            "created_at": utc_now_iso(),
            "source_build_id": build_id,
            "note": note,
        },
    )
    return path


def compare_baseline(
    project_dir: Path,
    *,
    template: str,
    width: int,
    height: int,
    fps_num: int,
    fps_den: int,
    visual: dict[str, Any],
    frame_sha256: dict[int, str] | None = None,
) -> BaselineComparison:
    """Compare this build's samples with a stored baseline, if any."""

    path = baseline_path(project_dir, template, width, height, fps_num, fps_den)
    relative = path.relative_to(project_dir).as_posix()
    if not path.is_file():
        return BaselineComparison(status="missing", path=relative)
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return BaselineComparison(
            status="drifted", path=relative, warnings=["baseline is not readable"]
        )
    sampled = list(visual.get("sampled_frames", []))
    if list(baseline.get("sampled_frames", [])) != sampled:
        return BaselineComparison(
            status="drifted",
            path=relative,
            warnings=["sample frame indices changed; rebuild the baseline"],
        )
    current = {frame["index"]: frame for frame in visual.get("frames", [])}
    stored = {frame["index"]: frame for frame in baseline.get("frames", [])}
    hashes = frame_sha256 or {}
    warnings: list[str] = []
    identical = True
    for index in sampled:
        before = stored.get(index, {})
        after = current.get(index, {})
        foreground = abs(
            float(after.get("foreground_ratio", 0.0)) - float(before.get("foreground_ratio", 0.0))
        )
        edges = abs(float(after.get("edge_ratio", 0.0)) - float(before.get("edge_ratio", 0.0)))
        if foreground > FOREGROUND_DRIFT:
            warnings.append(f"frame {index}: foreground drift {foreground:.3f}")
        if edges > EDGE_DRIFT:
            warnings.append(f"frame {index}: edge drift {edges:.3f}")
        stored_hash = str(before.get("sha256") or "")
        if stored_hash and hashes.get(index) and stored_hash != hashes[index]:
            identical = False
    return BaselineComparison(
        status="drifted" if warnings else "matched",
        path=relative,
        warnings=warnings,
        byte_identical=identical,
    )
