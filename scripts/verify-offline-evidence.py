"""Check the offline run's own evidence (P1.4).

Usage: python scripts/verify-offline-evidence.py --root <pytest basetemp>

Only completed render reports are judged. Cancellation and timeout reports are
expected to fail and are not evidence of an offline success. For every
completed build this asserts:

* the driver reached ``completed`` with the expected frame count;
* at least one external request was attempted and at least one failed, so the
  run demonstrates blocked network access rather than a silent request list;
* the build published a non-empty ``media/course.mp4``.

This deliberately uses only the standard library and reads files directly; the
project's verifier is a second, independent implementation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(root: Path) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    summaries: list[str] = []
    reports = sorted(root.rglob("report.json"))
    if not reports:
        return [f"no driver report.json under {root}"], summaries
    completed = 0
    for report_path in reports:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError:
            failures.append(f"{report_path}: report.json is not valid JSON")
            continue
        if report.get("mode") != "render" or report.get("terminal") != "completed":
            continue
        completed += 1
        build_root = report_path.parent.parent
        label = build_root.name
        frames = report.get("frames")
        expected = report.get("expected_frames")
        if report.get("finished") is not True:
            failures.append(f"{label}: finished is not true")
        if frames != expected:
            failures.append(f"{label}: {frames} frames, expected {expected}")
        requests = report.get("external_requests")
        if not isinstance(requests, list) or not requests:
            failures.append(f"{label}: no external request was attempted")
        if int(report.get("request_failures") or 0) <= 0:
            failures.append(f"{label}: no external request failed")
        video = build_root.parent.parent / "media" / "course.mp4"
        if not video.is_file() or video.stat().st_size == 0:
            failures.append(f"{label}: no published video at {video}")
        else:
            summaries.append(
                f"{label}: {frames} frames, {len(requests or [])} external attempts, "
                f"{report.get('request_failures')} failures, video {video.stat().st_size} bytes"
            )
    if completed == 0:
        failures.append("no completed render report was found")
    return failures, summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    failures, summaries = verify(args.root)
    for line in summaries:
        print(f"OK {line}")
    for line in failures:
        print(f"FAIL {line}")
    print(f"{len(summaries)} completed build(s), {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
