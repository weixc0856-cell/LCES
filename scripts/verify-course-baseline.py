#!/usr/bin/env python
"""Verify that a frozen course baseline still matches the project bytes.

    python scripts/verify-course-baseline.py \
        --baseline docs/design/p9/course-baseline-2026-10-24.json \
        --project projects/attention-is-all-you-need

Exit 0 only when every present file matches its recorded SHA-256. A file that
was present at freeze time but is missing now is reported as stale too; a path
recorded as absent is expected to stay absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(baseline_path: Path, project_dir: Path) -> list[str]:
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for item in data.get("files", []):
        relative = str(item.get("path", ""))
        path = project_dir / relative
        if not item.get("present", True):
            if path.exists():
                problems.append(f"appeared after freeze: {relative}")
            continue
        if not path.is_file():
            problems.append(f"missing after freeze: {relative}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item.get("sha256"):
            problems.append(f"changed after freeze: {relative}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    problems = verify(args.baseline, args.project)
    for line in problems:
        print(f"STALE {line}")
    data = json.loads(args.baseline.read_text(encoding="utf-8"))
    print(f"checked {len(data.get('files', []))} paths; {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
