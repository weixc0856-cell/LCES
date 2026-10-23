"""Human visual acceptance records (P2.4-D).

Automatic checks may fail an asset; they can never mark one as *accepted*.
This module records a person, a timestamp, the frames they looked at, the
toolchain that produced them and a verdict. The release gate requires such a
record when a build ships animation media: a green QA report is not a
substitute for someone having watched the result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from content_studio.media import ffmpeg_version
from content_studio.motion_canvas import (
    MOTION_CANVAS_VERSION,
    NODE_VERSION,
    PLAYWRIGHT_VERSION,
)
from content_studio.utils import utc_now_iso, write_json

SCHEMA_VERSION = "1.0"
RECORD_PATH = Path("internal") / "qa" / "visual_acceptance.json"
VERDICTS = frozenset({"pass", "fail"})


def current_toolchain() -> dict[str, str]:
    """The versions that invalidate an acceptance when they change."""

    return {
        "node_version": NODE_VERSION,
        "motion_canvas_version": MOTION_CANVAS_VERSION,
        "playwright_version": PLAYWRIGHT_VERSION,
        "ffmpeg_version": ffmpeg_version(),
    }


def load_records(project_dir: Path) -> list[dict[str, Any]]:
    path = project_dir / RECORD_PATH
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def record_acceptance(
    project_dir: Path,
    *,
    template: str,
    reviewer: str,
    frames: list[int],
    verdict: str,
    note: str = "",
) -> Path:
    """Append one human review. Machine checks never call this."""

    if not reviewer.strip():
        raise ValueError("reviewer must not be empty")
    if not frames:
        raise ValueError("at least one reviewed frame index is required")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VERDICTS)}")
    records = load_records(project_dir)
    records.append(
        {
            "template": template,
            "toolchain": current_toolchain(),
            "reviewer": reviewer.strip(),
            "reviewed_at": utc_now_iso(),
            "frames": [int(index) for index in frames],
            "verdict": verdict,
            "note": note,
        }
    )
    return write_json(
        project_dir / RECORD_PATH,
        {"schema_version": SCHEMA_VERSION, "records": records},
    )


def acceptance_problem(
    project_dir: Path, *, template: str, expected: dict[str, str] | None = None
) -> str:
    """Empty when a matching human acceptance exists, otherwise the reason."""

    expected = expected or current_toolchain()
    records = load_records(project_dir)
    if not records:
        return "没有人工视觉验收记录（lces accept-visual）"
    for record in records:
        if record.get("template") != template:
            continue
        if record.get("verdict") != "pass":
            continue
        if record.get("toolchain") != expected:
            continue
        if not record.get("frames"):
            continue
        if not str(record.get("reviewer") or "").strip():
            continue
        return ""
    return f"模板 {template} 没有与当前工具链匹配的通过记录"
