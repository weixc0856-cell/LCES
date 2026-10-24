"""Read-only summary of a real research run, for manual acceptance.

Usage::

    uv run python scripts/analyze-research-trial.py projects/<project>

It does not modify the project. The output is Markdown so it can be pasted
into an acceptance record.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from content_studio.ingestion import load_registry, load_source_text
from content_studio.research import load_evidence_ledger
from content_studio.source_map import ensure_source_map
from content_studio.utils import normalize_quote


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return re.sub(r"[\s§#.:()（）\-]+", "", value.lower())


def _section_for(locator: str, sections: list[str]) -> str:
    candidate = _norm(locator)
    if not candidate:
        return ""
    for section in sections:
        normalized = _norm(section)
        if normalized and (normalized in candidate or candidate in normalized):
            return section
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    project = args.project_dir.resolve()

    registry = load_registry(project)
    if registry is None:
        print("no source registry")
        return 1
    source_map = ensure_source_map(project, project.name, registry)
    chunks = {
        chunk.chunk_id: chunk for document in source_map.documents for chunk in document.chunks
    }

    analysis_payload = _load_json(project / "internal" / "research_analysis.json", {})
    calls = analysis_payload.get("research_calls", [])
    excluded_chunks = analysis_payload.get("excluded_chunks", [])
    excluded_ids = {item["chunk_id"] for item in excluded_chunks}
    claims = _load_json(project / "internal" / "claims.json", [])
    ledger = load_evidence_ledger(project)

    print(f"# Research trial: {project.name}")
    print()
    print(f"- source map: {len(chunks)} chunks, {len(source_map.documents)} source(s)")
    print(f"- research calls: {len(calls)}")
    print(f"- claims: {len(claims)} (key: {sum(1 for c in claims if c['importance'] == 'key')})")
    print(f"- evidence: {len(ledger.records)}")
    print(f"- merged claims: {analysis_payload.get('merged_claims', 'not recorded')}")
    audit = analysis_payload.get("quote_audit") or {}
    if audit:
        print(
            "- quote audit: "
            f"total={audit.get('total')} exact={audit.get('verified_exact')} "
            f"normalized={audit.get('verified_normalized')} "
            f"needs_review={audit.get('needs_review')} rejected={audit.get('rejected')}"
        )
    else:
        print("- quote audit: not recorded")
    print(
        f"- non-verbatim evidence: {analysis_payload.get('non_verbatim_evidence', 'not recorded')}"
    )
    print(f"- intentionally excluded chunks: {len(excluded_ids)}")
    print(f"- dropped evidence: {analysis_payload.get('dropped_evidence', 'n/a')}")
    print()

    print("## Calls")
    print()
    print("| # | source | chunks | section | pages | finish | in | out | request_id |")
    print("|---|---|---|---|---|---|---|---|---|")
    for call in calls:
        usage = call.get("usage") or {}
        first, last = call["chunk_ids"][0], call["chunk_ids"][-1]
        print(
            f"| {call['index']} | {call['source_id']} | {first}–{last} "
            f"({len(call['chunk_ids'])}) | {call.get('section', '')} | "
            f"{call.get('pages', '')} | {call.get('finish_reason', '')} | "
            f"{usage.get('input_tokens', '')} | {usage.get('output_tokens', '')} | "
            f"{call.get('request_id', '')} |"
        )
    print()

    sent: list[str] = []
    for call in calls:
        sent.extend(call["chunk_ids"])
    sent_counts = Counter(sent)
    missing = sorted(set(chunks) - set(sent) - excluded_ids)
    duplicated = sorted(chunk_id for chunk_id, count in sent_counts.items() if count > 1)
    unknown = sorted(set(sent) - set(chunks))
    print("## Chunk coverage")
    print()
    print(f"- sent once: {sum(1 for count in sent_counts.values() if count == 1)}")
    print(f"- missing: {', '.join(missing) if missing else 'none'}")
    print(f"- sent more than once: {', '.join(duplicated) if duplicated else 'none'}")
    excluded_sections = sorted({item["section"] for item in excluded_chunks})
    print(
        "- excluded by section: " + (", ".join(excluded_sections) if excluded_sections else "none")
    )
    print(f"- unknown chunk ids: {', '.join(unknown) if unknown else 'none'}")
    print()

    with_evidence = Counter(record.claim_id for record in ledger.records)
    without_evidence = [
        claim["claim_id"] for claim in claims if claim["claim_id"] not in with_evidence
    ]
    print("## Claim/evidence linkage")
    print()
    print(
        f"- claims without evidence: {', '.join(without_evidence) if without_evidence else 'none'}"
    )
    unknown_claims = sorted(
        {record.claim_id for record in ledger.records} - {claim["claim_id"] for claim in claims}
    )
    unknown_text = ", ".join(unknown_claims) if unknown_claims else "none"
    print(f"- evidence pointing at unknown claims: {unknown_text}")
    print()

    compared = 0
    unmatched: list[str] = []
    unverifiable: list[str] = []
    for record in ledger.records:
        excerpt = record.source_excerpt.strip()
        if not excerpt:
            unverifiable.append(record.evidence_id)
            continue
        source = load_source_text(project, record.source_id)
        if not source:
            unverifiable.append(record.evidence_id)
            continue
        normalized = normalize_quote(excerpt)
        if len(normalized) < 12:
            unverifiable.append(record.evidence_id)
            continue
        compared += 1
        if normalized not in normalize_quote(source):
            unmatched.append(record.evidence_id)
    print("## Evidence quotes")
    print()
    print(f"- compared: {compared}")
    print(f"- not found in source: {', '.join(unmatched) if unmatched else 'none'}")
    unverifiable_text = ", ".join(unverifiable) if unverifiable else "none"
    print(f"- unverifiable (missing/short/no source): {unverifiable_text}")
    print()

    sections: list[str] = []
    for document in source_map.documents:
        for chunk in document.chunks:
            if chunk.section and chunk.section not in sections:
                sections.append(chunk.section)
    by_section = Counter()
    unknown_locator = Counter()
    for record in ledger.records:
        section = _section_for(record.locator, sections)
        if section:
            by_section[section] += 1
        else:
            unknown_locator[record.locator or "(empty)"] += 1
    print("## Evidence by section")
    print()
    for section in sections:
        print(f"- {section}: {by_section.get(section, 0)}")
    no_evidence = [section for section in sections if by_section.get(section, 0) == 0]
    print()
    print(f"- sections with no evidence: {', '.join(no_evidence) if no_evidence else 'none'}")
    print(f"- locators not matched to a section: {dict(unknown_locator)}")
    print()

    haystack = " \n ".join(
        [claim["statement"] for claim in claims]
        + [record.source_excerpt for record in ledger.records]
        + [record.notes for record in ledger.records]
    ).lower()
    markers = {
        "28.4 BLEU": "28.4",
        "41.8 BLEU": "41.8",
        "Table 1": "table 1",
        "Table 2": "table 2",
        "Table 3": "table 3",
        "multi-head": "multi-head",
        "positional encoding": "positional",
        "scaled dot-product": "scaled dot-product",
        "complexity": "complexi",
        "limitation": "limitation",
    }
    print("## Key fact presence (string search, not semantic proof)")
    print()
    for label, needle in markers.items():
        print(f"- {label}: {'yes' if needle in haystack else 'NO'}")
    print()

    types = Counter(claim["claim_type"] for claim in claims)
    print("## Claim types")
    print()
    for name, count in sorted(types.items()):
        print(f"- {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
