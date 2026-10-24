"""Two-window trial for the deterministic evidence locator.

This is a validation harness, not the production research stage. It sends only
the attention window (§3.2.x) and the results window (§6.1/§6.2) to the model,
then locates every proposed quote with ``evidence_locator``. It writes a report
under ``var/quote-locator-trial/`` and does not modify the project.

Usage::

    uv run python scripts/trial-quote-locator.py projects/attention-is-all-you-need
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

from content_studio.evidence_locator import QuoteCandidate, validate_candidates
from content_studio.ingestion import load_registry, load_source_text
from content_studio.models import ProjectConfig, SectionAnalysis, SourceChunk
from content_studio.orchestrator import load_project_config
from content_studio.planning import load_paper_map
from content_studio.providers.base import GenerationRequest, Message
from content_studio.providers.factory import build_provider
from content_studio.research import SECTION_PROMPT, _pack_windows, _window_prompt
from content_studio.settings import get_settings
from content_studio.source_map import ensure_source_map
from content_studio.structured_evidence import (
    StructuredAudit,
    review_for,
    validate_structured_record,
)
from content_studio.utils import utc_now, write_json

GROUPS: dict[str, tuple[str, ...]] = {
    "A_attention": ("3.2",),
    "B_results": ("6 Results", "6.1", "6.2"),
}


def _selected(chunks: list[SourceChunk], prefixes: tuple[str, ...]) -> list[SourceChunk]:
    return [
        chunk
        for chunk in chunks
        if chunk.section and any(chunk.section.startswith(prefix) for prefix in prefixes)
    ]


def _read_cfg(project: Path) -> ProjectConfig:
    try:
        return load_project_config(project / "project.yaml")
    except Exception:
        return ProjectConfig(project_id=project.name, title=project.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("var/quote-locator-trial"))
    parser.add_argument("--provider", default="local")
    parser.add_argument("--budget", type=int, default=12000)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    config = _read_cfg(project)
    settings = get_settings()
    registry = load_registry(project)
    if registry is None or not registry.sources:
        print("no source registry")
        return 1
    source_map = ensure_source_map(project, config.project_id, registry)
    paper_map = load_paper_map(project)
    records = {record.source_id: record for record in registry.sources}
    provider = build_provider(settings, args.provider)
    max_tokens = min(settings.max_output_tokens, settings.research_max_output_tokens)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    map_bytes = (project / "internal" / "source_map.json").read_bytes()
    (output / "source_map.json").write_bytes(map_bytes)
    for source_id in records:
        source_path = project / "internal" / "sources" / f"{source_id}.txt"
        if source_path.is_file():
            (output / f"{source_id}.txt").write_bytes(source_path.read_bytes())
    report: list[str] = [
        "# Quote locator trial",
        "",
        f"- generated_at: {utc_now().isoformat()}",
        f"- project: `{config.project_id}`",
        f"- provider/model: `{provider.name}` / `{provider.model}`",
        f"- source chunks: {sum(len(document.chunks) for document in source_map.documents)}",
        f"- source_map sha256: {hashlib.sha256(map_bytes).hexdigest()}",
        f"- window budget: {args.budget} chars; output cap: {max_tokens} tokens",
        "",
    ]
    all_candidates: list[dict[str, object]] = []
    total_started = time.perf_counter()

    for group, prefixes in GROUPS.items():
        report += [f"## {group}", ""]
        for document in source_map.documents:
            record = records.get(document.source_id)
            if record is None:
                continue
            selected = _selected(document.chunks, prefixes)
            if not selected:
                report += [f"No chunks matched {prefixes}.", ""]
                continue
            document_text = load_source_text(project, document.source_id)
            windows = _pack_windows(
                project,
                document,
                args.budget,
                selected,
                max_sections=10,
                min_chars=0,
            )
            for window in windows:
                request = GenerationRequest(
                    messages=[
                        Message("system", SECTION_PROMPT),
                        Message("user", _window_prompt(config, record, window, paper_map)),
                    ],
                    max_tokens=max_tokens,
                    metadata={
                        "project_id": config.project_id,
                        "title": config.title,
                        "source_ids": document.source_id,
                        "chunk_ids": ",".join(window.chunk_ids),
                        "stage": "research",
                    },
                )
                started = time.perf_counter()
                section = provider.generate_structured(request, SectionAnalysis)
                elapsed = time.perf_counter() - started
                last = provider.last_result
                chunk_map = {chunk.chunk_id: chunk for chunk in window.chunks}
                structured_records = [
                    evidence
                    for evidence in section.evidence
                    if evidence.evidence_type in {"formula", "table"}
                ]
                quote_records = [
                    evidence
                    for evidence in section.evidence
                    if evidence.evidence_type not in {"formula", "table"}
                ]
                candidates = [
                    QuoteCandidate(
                        candidate_id=evidence.evidence_id,
                        claim_id=evidence.claim_id,
                        source_id=evidence.source_id,
                        chunk_id=evidence.chunk_id,
                        locator=evidence.locator,
                        text=evidence.source_excerpt,
                    )
                    for evidence in quote_records
                ]
                located, audit = validate_candidates(
                    candidates,
                    claim_ids={claim.claim_id for claim in section.claims},
                    chunks=chunk_map,
                    source_texts={document.source_id: document_text},
                )
                structured_audit = StructuredAudit()
                structured_locations = []
                for evidence in structured_records:
                    location = validate_structured_record(
                        evidence,
                        paper_map=paper_map,
                        chunks=chunk_map,
                        source_texts={document.source_id: document_text},
                    )
                    structured_audit.total += 1
                    if location.reason:
                        structured_audit.reasons[location.reason] = (
                            structured_audit.reasons.get(location.reason, 0) + 1
                        )
                    if location.status == "verified_structured":
                        structured_audit.verified_structured += 1
                    elif location.status == "needs_review":
                        structured_audit.needs_review += 1
                        structured_audit.reviews.append(review_for(evidence, location))
                    else:
                        structured_audit.rejected += 1
                        structured_audit.reviews.append(review_for(evidence, location))
                    structured_locations.append((evidence, location))
                claim_text = {claim.claim_id: claim.statement for claim in section.claims}
                usage = last.usage.as_dict() if last else {}
                report += [
                    f"### {window.chunk_ids[0]}–{window.chunk_ids[-1]}",
                    "",
                    f"- sections: {window.section}",
                    f"- chunks: {len(window.chunk_ids)}; chars: {len(window.text)}",
                    f"- elapsed: {elapsed:.1f}s; usage: {usage}; "
                    f"finish_reason: {last.finish_reason if last else ''}",
                    f"- quote candidates: {audit.total}; exact: {audit.verified_exact}; "
                    f"normalized: {audit.verified_normalized}; "
                    f"needs_review: {audit.needs_review}; rejected: {audit.rejected}",
                    f"- structured candidates: {structured_audit.total}; "
                    f"verified_structured: {structured_audit.verified_structured}; "
                    f"needs_review: {structured_audit.needs_review}; "
                    f"rejected: {structured_audit.rejected}",
                    "",
                    "| candidate | claim | status | reason | locator | excerpt |",
                    "|---|---|---|---|---|---|",
                ]
                for item in located:
                    excerpt = item.location.excerpt.replace("|", "\\|")[:160]
                    report.append(
                        f"| {item.candidate.candidate_id} | {item.candidate.claim_id} | "
                        f"{item.location.status} | {item.location.reason} | "
                        f"{item.location.locator} | {excerpt} |"
                    )
                report += [
                    "",
                    "| structured | kind | status | reason | fields | excerpt |",
                    "|---|---|---|---|---|---|",
                ]
                for structured, location in structured_locations:
                    if structured.formula is not None:
                        fields = (
                            f"{structured.formula.formula_id} | "
                            f"{structured.formula.expression} | "
                            f"{', '.join(structured.formula.symbols)}"
                        )
                    elif structured.table is not None:
                        fields = (
                            f"{structured.table.table_id} | {structured.table.row_label} | "
                            f"{structured.table.column_label} | {structured.table.value} "
                            f"{structured.table.unit} | {structured.table.variant}"
                        )
                    else:
                        fields = ""
                    excerpt = location.excerpt.replace("|", "\\|")[:160]
                    report.append(
                        f"| {structured.evidence_id} | {structured.evidence_type} | "
                        f"{location.status} | {location.reason} | "
                        f"{fields.replace('|', '\\|')} | {excerpt} |"
                    )
                report += ["", "#### Claim statements", ""]
                for claim in section.claims:
                    label = f"- **{claim.claim_id}** ({claim.claim_type}/{claim.importance}): "
                    report.append(label + claim.statement)
                    report.append("")
                for item in located:
                    all_candidates.append(
                        {
                            "group": group,
                            "kind": "quote",
                            "source_id": item.candidate.source_id,
                            "chunk_id": item.location.chunk_id,
                            "candidate_id": item.candidate.candidate_id,
                            "claim_id": item.candidate.claim_id,
                            "claim": claim_text.get(item.candidate.claim_id, ""),
                            "status": item.location.status,
                            "reason": item.location.reason,
                            "candidate": item.candidate.text,
                            "excerpt": item.location.excerpt,
                            "locator": item.location.locator,
                            "char_start": item.location.char_start,
                            "char_end": item.location.char_end,
                        }
                    )
                for structured, location in structured_locations:
                    if structured.formula is not None:
                        structured_payload = structured.formula.model_dump()
                    elif structured.table is not None:
                        structured_payload = structured.table.model_dump()
                    else:
                        structured_payload = {}
                    all_candidates.append(
                        {
                            "group": group,
                            "kind": structured.evidence_type,
                            "source_id": structured.source_id,
                            "chunk_id": location.chunk_id,
                            "candidate_id": structured.evidence_id,
                            "claim_id": structured.claim_id,
                            "claim": claim_text.get(structured.claim_id, ""),
                            "status": location.status,
                            "reason": location.reason,
                            "candidate": "",
                            "structured": structured_payload,
                            "excerpt": location.excerpt,
                            "locator": location.locator,
                            "char_start": location.char_start,
                            "char_end": location.char_end,
                        }
                    )
                report += [
                    "",
                    "#### Review queue",
                    "",
                ]
                if audit.reviews or structured_audit.reviews:
                    for review in audit.reviews:
                        report.append(
                            f"- {review.candidate_id} ({review.status}/{review.reason}): "
                            f"{review.candidate[:200]}"
                        )
                    for review in structured_audit.reviews:
                        report.append(
                            f"- {review.candidate_id} ({review.kind}/{review.status}/"
                            f"{review.reason}): {review.detail[:200]}"
                        )
                else:
                    report.append("- (empty)")
                report.append("")

    total_elapsed = time.perf_counter() - total_started
    report += ["## Summary", "", f"- total elapsed: {total_elapsed:.1f}s", ""]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    write_json(
        output / "candidates.json",
        {"generated_at": utc_now(), "candidates": all_candidates},
    )
    print(f"report: {output / 'report.md'}")
    provider.close() if hasattr(provider, "close") else None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
