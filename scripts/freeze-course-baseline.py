#!/usr/bin/env python
"""Write a read-only course baseline for P9 (or any later phase).

    python scripts/freeze-course-baseline.py \
        --project projects/attention-is-all-you-need \
        --out docs/design/p9/course-baseline-2026-10-24-r2.json \
        --supersedes docs/design/p9/course-baseline-2026-10-24.json

The script never writes into the project. It records SHA-256 for the content,
narration, contract, evidence, reviews, reports and build output, plus the
derived decisions so a later review can tell exactly what was frozen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

FILES = (
    "content/public_content.json",
    "content/reading_edition.json",
    "content/outline.json",
    "internal/speaker_script.json",
    "internal/plan/course_contract.json",
    "internal/source_registry.json",
    "internal/evidence_ledger.csv",
    "internal/claims.json",
    "internal/qa/structured_evidence_review.json",
    "internal/qa/course_content_audit.json",
    "internal/qa/course_quality_audit.json",
    "internal/qa/qa_report.json",
    "internal/qa/timing_evidence.json",
    "internal/qa/visual_assets.json",
    "internal/qa/quote_audit.json",
    "build/slides/index.html",
    "build/reading_edition.html",
)


def _load(project: Path, relative: str) -> dict:
    return json.loads((project / relative).read_text(encoding="utf-8"))


def _evidence_rows(project: Path) -> int:
    path = project / "internal" / "evidence_ledger.csv"
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get("evidence_id"))


def freeze(project: Path, supersedes: str = "") -> dict:
    files = []
    for relative in FILES:
        path = project / relative
        if not path.is_file():
            files.append({"path": relative, "present": False})
            continue
        files.append(
            {
                "path": relative,
                "present": True,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    contract = _load(project, "internal/plan/course_contract.json")
    qa = _load(project, "internal/qa/qa_report.json")
    audit = _load(project, "internal/qa/course_content_audit.json")
    quality = _load(project, "internal/qa/course_quality_audit.json")
    timing = _load(project, "internal/qa/timing_evidence.json")
    review = _load(project, "internal/qa/structured_evidence_review.json")
    claims = json.loads((project / "internal/claims.json").read_text(encoding="utf-8"))
    items = review.get("items", []) if isinstance(review, dict) else []
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "project_id": contract.get("project_id") or project.name,
        "note": (
            "Read-only baseline. No course content, narration, contract, evidence or build "
            "output was regenerated or edited by this script."
        ),
        "supersedes": supersedes,
        "course_contract": {
            "version": contract.get("version"),
            "status": contract.get("status"),
            "target_duration_minutes": contract.get("target_duration_minutes"),
            "duration_status": contract.get("duration_status", "planning_target"),
            "deferred_deliverables": contract.get("deferred_deliverables", []),
            "manual_items": contract.get("manual_items", []),
        },
        "counts": {
            "claims": len(claims),
            "evidence_rows": _evidence_rows(project),
            "review_items": len(items),
            "review_pending": sum(
                1 for item in items if item.get("conclusion", "pending") == "pending"
            ),
        },
        "qa": {
            "content_version": qa.get("content_version"),
            "gates": {
                gate: sorted(
                    {check["status"] for check in qa.get("checks", []) if check.get("gate") == gate}
                )
                for gate in ("gate_1_research", "gate_2_content", "gate_3_engineering")
            },
        },
        "course_content_audit": {
            "decision": audit.get("decision"),
            "course_version": audit.get("course_version"),
            "summary": audit.get("summary"),
        },
        "course_product": {
            "decision": quality.get("decision"),
            "content_version": quality.get("content_version"),
            "summary": quality.get("summary"),
        },
        "timing": {
            "method": timing.get("method"),
            "measured_seconds": timing.get("measured_seconds"),
            "script_sha256": timing.get("script_sha256"),
        },
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--supersedes", default="")
    args = parser.parse_args()
    payload = freeze(args.project, args.supersedes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(payload['files'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
