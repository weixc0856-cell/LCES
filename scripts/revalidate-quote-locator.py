"""Re-validate a saved candidate batch with section-level resolution.

No model calls. The same candidate texts and declared chunks are re-run through
the locator; the report shows the status delta and which candidates were
resolved to a different chunk within the same section.

Usage::

    uv run python scripts/revalidate-quote-locator.py projects/attention-is-all-you-need
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from content_studio.evidence_locator import QuoteCandidate, validate_candidates
from content_studio.ingestion import load_source_text
from content_studio.source_map import load_source_map
from content_studio.utils import utc_now


def _load(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("candidates", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("var/quote-locator-trial/candidates.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("var/quote-locator-retrial"))
    args = parser.parse_args()

    project = args.project_dir.resolve()
    old = _load(args.candidates)
    source_map = load_source_map(project)
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
    claim_ids = {item["claim_id"] for item in old}

    candidates = [
        QuoteCandidate(
            candidate_id=item["candidate_id"],
            claim_id=item["claim_id"],
            source_id=item["source_id"],
            chunk_id=item.get("chunk_id", ""),
            locator=item.get("locator", ""),
            text=item.get("candidate", ""),
        )
        for item in old
    ]
    located, audit = validate_candidates(
        candidates,
        claim_ids=claim_ids,
        chunks=chunks,
        source_texts=source_texts,
    )

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    map_path = project / "internal" / "source_map.json"
    map_bytes = map_path.read_bytes()
    (output / "source_map.json").write_bytes(map_bytes)
    for source_id in source_texts:
        source_path = project / "internal" / "sources" / f"{source_id}.txt"
        if source_path.is_file():
            (output / f"{source_id}.txt").write_bytes(source_path.read_bytes())

    old_counts = {"verified_exact": 0, "verified_normalized": 0, "needs_review": 0, "rejected": 0}
    new_counts = {"verified_exact": 0, "verified_normalized": 0, "needs_review": 0, "rejected": 0}
    rows: list[str] = []
    changes: list[str] = []
    exported: list[dict] = []
    for index, (item, item_new) in enumerate(zip(old, located, strict=True)):
        old_counts[item["status"]] = old_counts.get(item["status"], 0) + 1
        new_counts[item_new.location.status] = new_counts.get(item_new.location.status, 0) + 1
        changed = (
            item["status"] != item_new.location.status
            or item.get("chunk_id", "") != item_new.location.chunk_id
        )
        rows.append(
            f"| {item.get('group', '')} | {item['candidate_id']} | {item['status']} | "
            f"{item.get('reason', '')} | {item_new.location.status} | "
            f"{item_new.location.reason} | {item.get('chunk_id', '')} -> "
            f"{item_new.location.chunk_id} | {item_new.location.resolved} | "
            f"{item_new.location.excerpt[:90].replace('|', '\\|')} |"
        )
        if changed:
            changes.append(
                f"- {item.get('group', '')} {item['candidate_id']}: "
                f"`{item['status']}` -> `{item_new.location.status}`; "
                f"chunk `{item.get('chunk_id', '')}` -> `{item_new.location.chunk_id}`; "
                f"reason `{item_new.location.reason}`"
            )
        exported.append(
            {
                "index": index,
                "group": item.get("group", ""),
                "old_status": item["status"],
                "old_reason": item.get("reason", ""),
                "old_chunk_id": item.get("chunk_id", ""),
                "new_status": item_new.location.status,
                "new_reason": item_new.location.reason,
                "new_chunk_id": item_new.location.chunk_id,
                "resolved": item_new.location.resolved,
                "claim_id": item["claim_id"],
                "candidate": item.get("candidate", ""),
                "excerpt": item_new.location.excerpt,
                "locator": item_new.location.locator,
            }
        )

    report = [
        "# Quote locator re-validation (section-level resolution)",
        "",
        f"- generated_at: {utc_now().isoformat()}",
        f"- project: `{project.name}`",
        f"- candidates: `{args.candidates}`",
        f"- source_map sha256: `{hashlib.sha256(map_bytes).hexdigest()}`",
        "",
        "## Counts",
        "",
        "| status | old | new |",
        "|---|---|---|",
    ]
    for status in ("verified_exact", "verified_normalized", "needs_review", "rejected"):
        report.append(f"| {status} | {old_counts.get(status, 0)} | {new_counts.get(status, 0)} |")
    report += [
        "",
        f"- section-resolved: {audit.section_resolved}",
        f"- audit reasons: {audit.reasons}",
        "",
        "## Changes",
        "",
        *(changes or ["- (none)"]),
        "",
        "## All candidates",
        "",
        "| group | candidate | old | old reason | new | new reason | chunk | resolved | excerpt |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    (output / "candidates.json").write_text(
        json.dumps(
            {"generated_at": utc_now().isoformat(), "candidates": exported},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"report: {output / 'report.md'}")
    print(
        f"old exact={old_counts.get('verified_exact', 0)} "
        f"new exact={new_counts.get('verified_exact', 0)} "
        f"section_resolved={audit.section_resolved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
