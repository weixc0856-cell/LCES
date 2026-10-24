"""Re-validate saved structured formula/table candidates without the model.

Usage::

    uv run python scripts/revalidate-structured-evidence.py projects/<project> \
        --candidates var/quote-locator-stage-b2/candidates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from content_studio.ingestion import load_source_text
from content_studio.models import EvidenceRecord
from content_studio.planning import load_paper_map
from content_studio.source_map import load_source_map
from content_studio.structured_evidence import validate_structured_record
from content_studio.utils import utc_now


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("var/quote-locator-stage-b2/candidates.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("var/structured-evidence-retrial"))
    args = parser.parse_args()

    project = args.project_dir.resolve()
    payload = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    source_map = load_source_map(project)
    paper_map = load_paper_map(project)
    if source_map is None:
        print("no source map")
        return 1
    chunks = {
        chunk.chunk_id: chunk for document in source_map.documents for chunk in document.chunks
    }
    source_texts = {
        document.source_id: load_source_text(project, document.source_id)
        for document in source_map.documents
    }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    map_path = project / "internal" / "source_map.json"
    map_bytes = map_path.read_bytes()
    (output / "source_map.json").write_bytes(map_bytes)
    for source_id in source_texts:
        source_path = project / "internal" / "sources" / f"{source_id}.txt"
        if source_path.is_file():
            (output / f"{source_id}.txt").write_bytes(source_path.read_bytes())

    rows: list[str] = []
    changes: list[str] = []
    counts = {"old": {}, "new": {}}
    for item in candidates:
        structured = item.get("structured") or {}
        kind = item.get("kind", "")
        if kind not in {"formula", "table"} or not structured:
            continue
        record = EvidenceRecord(
            evidence_id=item["candidate_id"],
            source_id=item["source_id"],
            chunk_id=item.get("chunk_id", ""),
            claim_id=item["claim_id"],
            evidence_type=kind,
            support_relation="supports",
            formula=structured if kind == "formula" else None,
            table=structured if kind == "table" else None,
        )
        location = validate_structured_record(
            record,
            paper_map=paper_map,
            chunks=chunks,
            source_texts=source_texts,
        )
        old_status = item.get("status", "")
        counts["old"][old_status] = counts["old"].get(old_status, 0) + 1
        counts["new"][location.status] = counts["new"].get(location.status, 0) + 1
        if old_status != location.status:
            changes.append(
                f"- {kind} {item['candidate_id']}: `{old_status}` -> "
                f"`{location.status}` (`{location.reason}`)"
            )
        rows.append(
            f"| {kind} | {item['candidate_id']} | {old_status} | {location.status} | "
            f"{location.reason} | {location.excerpt[:100].replace('|', '\\|')} |"
        )

    report = [
        "# Structured evidence re-validation",
        "",
        f"- generated_at: {utc_now().isoformat()}",
        f"- source_map sha256: `{hashlib.sha256(map_bytes).hexdigest()}`",
        f"- candidates: `{args.candidates}`",
        "",
        "## Counts",
        "",
        "| status | old | new |",
        "|---|---|---|",
    ]
    for status in ("verified_structured", "needs_review", "rejected"):
        report.append(
            f"| {status} | {counts['old'].get(status, 0)} | {counts['new'].get(status, 0)} |"
        )
    report += ["", "## Changes", "", *(changes or ["- (none)"]), ""]
    report += [
        "## Candidates",
        "",
        "| kind | candidate | old | new | reason | excerpt |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"report: {output / 'report.md'}")
    print(f"old={counts['old']} new={counts['new']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
