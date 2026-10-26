#!/usr/bin/env python
"""Read-only preflight for P9-D2 per-scene recording.

    python scripts/preflight-scene-recordings.py \
        --project projects/attention-is-all-you-need \
        --out var/scene-preflight

It checks what can be checked without a person at the screen:

- the built deck has one section per content slide and a scene deep link;
- keyboard navigation and hash restore exist;
- no external assets and no raw LaTeX in visible text;
- the reading edition exists;
- the stored browser QA checks passed (read from qa_report.json, not re-run);
- whether any recording files exist yet (absence is NOT_RUN, not a pass).

Visual quality, animation meaning, audio sync and actual recording remain
human work and are always reported as NOT_RUN here.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

EXTERNAL = re.compile(r"""(?:src|href)=["']https?://""", re.IGNORECASE)
RAW_LATEX = re.compile(r"\\(?:frac|sqrt|mathrm|left|right|sum|mathbf)\b")
KEYBOARD_MARKERS = ("ArrowRight", "ArrowLeft", "Home", "End")


def deck_checks(html: str, slide_ids: list[str]) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    checks: list[dict] = []
    present = {
        section.get("id", "")
        for section in soup.find_all("section", id=True)
        if section.get("id", "").startswith("slide-")
    }
    missing = sorted(set(slide_ids) - present)
    extra = sorted(present - set(slide_ids))
    checks.append(
        {
            "check_id": "scene_sections",
            "status": "fail" if missing or extra else "pass",
            "detail": f"missing={missing or 'none'}; extra={extra or 'none'}",
        }
    )

    keyboard = [marker for marker in KEYBOARD_MARKERS if marker in html]
    checks.append(
        {
            "check_id": "keyboard_navigation",
            "status": "pass" if len(keyboard) == len(KEYBOARD_MARKERS) else "fail",
            "detail": "found: " + ", ".join(keyboard),
        }
    )

    deeplink = "location.hash" in html and "history.replaceState" in html
    checks.append(
        {
            "check_id": "scene_deeplink",
            "status": "pass" if deeplink else "fail",
            "detail": "location.hash + replaceState present" if deeplink else "no hash restore",
        }
    )

    external = EXTERNAL.findall(html)
    checks.append(
        {
            "check_id": "offline_assets",
            "status": "fail" if external else "pass",
            "detail": f"{len(external)} external reference(s)" if external else "no external refs",
        }
    )

    raw = RAW_LATEX.findall(soup.get_text(" "))
    checks.append(
        {
            "check_id": "no_raw_latex",
            "status": "fail" if raw else "pass",
            "detail": "raw commands: " + ", ".join(sorted(set(raw))) if raw else "none",
        }
    )
    return checks


def preflight(project: Path) -> dict:
    public = json.loads((project / "content" / "public_content.json").read_text(encoding="utf-8"))
    slide_ids = [slide["slide_id"] for slide in public.get("slides", [])]
    deck_path = project / "build" / "slides" / "index.html"
    html = deck_path.read_text(encoding="utf-8") if deck_path.is_file() else ""
    checks = (
        deck_checks(html, slide_ids)
        if html
        else [
            {
                "check_id": "deck_present",
                "status": "fail",
                "detail": "build/slides/index.html is missing",
            }
        ]
    )

    reading = project / "build" / "reading_edition.html"
    checks.append(
        {
            "check_id": "reading_present",
            "status": "pass" if reading.is_file() else "fail",
            "detail": reading.name if reading.is_file() else "missing",
        }
    )

    qa_path = project / "internal" / "qa" / "qa_report.json"
    if qa_path.is_file():
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        statuses = {item["check_id"]: item["status"] for item in qa.get("checks", [])}
        needed = ("browser_pages_load", "browser_layout_no_overflow")
        failed = [name for name in needed if statuses.get(name) != "pass"]
        checks.append(
            {
                "check_id": "browser_qa_recorded",
                "status": "pass" if not failed else "not_run",
                "detail": "browser checks pass" if not failed else f"not pass: {failed}",
            }
        )
    else:
        checks.append(
            {
                "check_id": "browser_qa_recorded",
                "status": "not_run",
                "detail": "internal/qa/qa_report.json missing",
            }
        )

    recordings = project / "build" / "recordings"
    files = sorted(recordings.glob("*.mp4")) if recordings.is_dir() else []
    checks.append(
        {
            "check_id": "recordings_present",
            "status": "pass" if files else "not_run",
            "detail": f"{len(files)} mp4 file(s)"
            if files
            else "no recordings yet (D2 not started)",
        }
    )
    checks.append(
        {
            "check_id": "human_visual_and_sync",
            "status": "not_run",
            "detail": "requires a person at 1920x1080/2560x1440; not automatable",
        }
    )
    return {
        "project_id": public.get("project_id", ""),
        "note": "Read-only preflight. NOT_RUN is not a pass.",
        "slides": len(slide_ids),
        "checks": checks,
        "summary": {
            "pass": sum(1 for item in checks if item["status"] == "pass"),
            "fail": sum(1 for item in checks if item["status"] == "fail"),
            "not_run": sum(1 for item in checks if item["status"] == "not_run"),
        },
    }


def render(report: dict) -> str:
    lines = [
        "# P9-D2 场景录制预检（只读）",
        "",
        f"**项目：** `{report['project_id']}`；内容场景：{report['slides']}",
        "",
        f"**汇总：** pass={report['summary']['pass']}，fail={report['summary']['fail']}，"
        f"NOT_RUN={report['summary']['not_run']}",
        "",
        "| 检查 | 状态 | 说明 |",
        "|---|---|---|",
    ]
    for item in report["checks"]:
        lines.append(f"| `{item['check_id']}` | {item['status']} | {item['detail']} |")
    lines.extend(
        [
            "",
            "> `NOT_RUN` 不代表通过。公式可读性、动画含义、音画同步、独立复位/录制仍需人工",
            "> 在目标分辨率下逐场景检查；复位方式为重新打开",
            "> `index.html#slide-XXX`（页面初始状态）。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Output prefix (no suffix)")
    args = parser.parse_args()
    report = preflight(args.project.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    md_path = args.out.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render(report), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"pass={report['summary']['pass']} fail={report['summary']['fail']} "
        f"not_run={report['summary']['not_run']}"
    )
    return 1 if report["summary"]["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
