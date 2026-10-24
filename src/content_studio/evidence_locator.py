"""Deterministic quote location for research evidence.

The model may propose a quote, but only this module turns a candidate into
formal evidence. A candidate must be found inside the chunk it names, with a
unique match; the excerpt written to the ledger is sliced from the source
text. A candidate that only matches after deleting or reordering content is
never accepted as a quote.

Only typography is normalised (quotes, dashes, invisible characters,
whitespace, case). Math symbols are left untouched, so ``√d_k`` does not
silently match ``\\sqrt{d_k}``; such a candidate goes to review.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from content_studio.models import SourceChunk, StrictModel
from content_studio.utils import normalize_quote, normalize_quote_with_map

QuoteStatus = Literal[
    "verified_exact",
    "verified_normalized",
    "needs_review",
    "rejected",
]
MIN_QUOTE_CHARS = 12


class QuoteCandidate(StrictModel):
    """One model-proposed quote, before any deterministic check."""

    candidate_id: str
    claim_id: str
    source_id: str
    chunk_id: str = ""
    section_id: str = ""
    locator: str = ""
    text: str


class QuoteLocation(StrictModel):
    status: QuoteStatus
    excerpt: str = ""
    reason: str = ""
    chunk_id: str = ""
    locator: str = ""
    char_start: int = 0
    char_end: int = 0
    normalized: bool = False
    # True when the quote was found in a chunk of the named section rather
    # than in the chunk the model named. The quote still lives in one chunk.
    resolved: bool = False


class QuoteReview(StrictModel):
    candidate_id: str
    claim_id: str
    source_id: str
    chunk_id: str = ""
    status: QuoteStatus
    reason: str
    candidate: str
    locator: str = ""


class QuoteAudit(StrictModel):
    total: int = 0
    verified_exact: int = 0
    verified_normalized: int = 0
    needs_review: int = 0
    rejected: int = 0
    section_resolved: int = 0
    reasons: dict[str, int] = Field(default_factory=dict)
    reviews: list[QuoteReview] = Field(default_factory=list)

    @property
    def accepted(self) -> int:
        return self.verified_exact + self.verified_normalized


class LocatedCandidate(StrictModel):
    candidate: QuoteCandidate
    location: QuoteLocation


def _locator_for(chunk: SourceChunk) -> str:
    if chunk.section:
        return f"§{chunk.section}"
    if chunk.page is not None:
        return f"p.{chunk.page}"
    return ""


def _result(
    candidate: QuoteCandidate,
    chunk: SourceChunk,
    status: QuoteStatus,
    *,
    reason: str = "",
    excerpt: str = "",
    char_start: int = 0,
    char_end: int = 0,
    normalized: bool = False,
) -> QuoteLocation:
    return QuoteLocation(
        status=status,
        excerpt=excerpt,
        reason=reason,
        chunk_id=candidate.chunk_id or chunk.chunk_id,
        locator=_locator_for(chunk),
        char_start=char_start,
        char_end=char_end,
        normalized=normalized,
    )


def locate_candidate(
    candidate: QuoteCandidate,
    *,
    chunk: SourceChunk,
    source_text: str,
) -> QuoteLocation:
    """Locate *candidate* inside *chunk* only; never search other chunks."""

    needle = candidate.text.strip()
    if not needle:
        return _result(candidate, chunk, "rejected", reason="empty_candidate")
    if len(normalize_quote(needle)) < MIN_QUOTE_CHARS:
        return _result(candidate, chunk, "needs_review", reason="too_short")

    chunk_text = source_text[chunk.char_start : chunk.char_end]
    exact_count = chunk_text.count(needle)
    if exact_count == 1:
        relative = chunk_text.index(needle)
        start = chunk.char_start + relative
        end = start + len(needle)
        return _result(
            candidate,
            chunk,
            "verified_exact",
            excerpt=source_text[start:end],
            char_start=start,
            char_end=end,
        )
    if exact_count > 1:
        return _result(candidate, chunk, "needs_review", reason="ambiguous_exact")

    normalized_candidate = normalize_quote(needle)
    normalized_chunk, index_map = normalize_quote_with_map(chunk_text)
    normalized_count = normalized_chunk.count(normalized_candidate)
    if normalized_count == 0:
        return _result(candidate, chunk, "needs_review", reason="not_found")
    if normalized_count > 1:
        return _result(candidate, chunk, "needs_review", reason="ambiguous_normalized")

    position = normalized_chunk.index(normalized_candidate)
    relative_start = index_map[position]
    relative_end = index_map[position + len(normalized_candidate) - 1] + 1
    start = chunk.char_start + relative_start
    end = chunk.char_start + relative_end
    return _result(
        candidate,
        chunk,
        "verified_normalized",
        excerpt=source_text[start:end],
        char_start=start,
        char_end=end,
        normalized=True,
    )


def _review(candidate: QuoteCandidate, location: QuoteLocation) -> QuoteReview:
    return QuoteReview(
        candidate_id=candidate.candidate_id,
        claim_id=candidate.claim_id,
        source_id=candidate.source_id,
        chunk_id=location.chunk_id or candidate.chunk_id,
        status=location.status,
        reason=location.reason,
        candidate=candidate.text[:500],
        locator=location.locator or candidate.locator,
    )


def validate_candidates(
    candidates: list[QuoteCandidate],
    *,
    claim_ids: set[str],
    chunks: dict[str, SourceChunk],
    source_texts: dict[str, str],
) -> tuple[list[LocatedCandidate], QuoteAudit]:
    """Validate every candidate against the current window's chunks."""

    located: list[LocatedCandidate] = []
    audit = QuoteAudit()
    chunks_by_section = _chunks_by_section(chunks)
    for candidate in candidates:
        audit.total += 1
        chunk = chunks.get(candidate.chunk_id) if candidate.chunk_id else None
        if chunk is None and candidate.locator in chunks:
            # Some models put the chunk id in ``locator``; accept that only
            # when the chunk belongs to this window.
            chunk = chunks[candidate.locator]
            candidate = candidate.model_copy(update={"chunk_id": chunk.chunk_id})

        section = _section_hint(candidate, chunk, chunks_by_section)
        if candidate.claim_id not in claim_ids:
            location = _invalid(candidate, "unknown_claim")
        elif candidate.source_id not in source_texts:
            location = _invalid(candidate, "unknown_source")
        elif chunk is not None and chunk.chunk_id.split(":", 1)[0] != candidate.source_id:
            location = _invalid(candidate, "chunk_source_mismatch")
        elif chunk is None and not section:
            location = _invalid(candidate, "unknown_chunk")
        else:
            source_text = source_texts[candidate.source_id]
            location = (
                locate_candidate(candidate, chunk=chunk, source_text=source_text)
                if chunk is not None
                else QuoteLocation(status="needs_review", reason="not_found_in_section")
            )
            if location.status not in {"verified_exact", "verified_normalized"} and section:
                resolved = _resolve_in_section(candidate, section, chunks_by_section, source_text)
                if resolved is not None:
                    if resolved.status in {"verified_exact", "verified_normalized"}:
                        audit.section_resolved += 1
                    location = resolved

        located.append(LocatedCandidate(candidate=candidate, location=location))
        audit.reasons[location.reason] = audit.reasons.get(location.reason, 0) + 1
        if location.status == "verified_exact":
            audit.verified_exact += 1
        elif location.status == "verified_normalized":
            audit.verified_normalized += 1
        elif location.status == "needs_review":
            audit.needs_review += 1
            audit.reviews.append(_review(candidate, location))
        else:
            audit.rejected += 1
            audit.reviews.append(_review(candidate, location))
        audit.reasons.pop("", None)
    return located, audit


def _chunks_by_section(chunks: dict[str, SourceChunk]) -> dict[str, list[SourceChunk]]:
    grouped: dict[str, list[SourceChunk]] = {}
    for chunk in chunks.values():
        if chunk.section:
            grouped.setdefault(chunk.section, []).append(chunk)
    for items in grouped.values():
        items.sort(key=lambda chunk: chunk.index)
    return grouped


def _section_hint(
    candidate: QuoteCandidate,
    chunk: SourceChunk | None,
    chunks_by_section: dict[str, list[SourceChunk]],
) -> str:
    if candidate.section_id:
        return candidate.section_id
    locator = candidate.locator.strip()
    if locator:
        if locator.startswith("§"):
            locator = locator[1:].strip()
        for section in chunks_by_section:
            if locator == section or locator in section:
                return section
    if chunk is not None and chunk.section:
        return chunk.section
    return ""


def _resolve_in_section(
    candidate: QuoteCandidate,
    section: str,
    chunks_by_section: dict[str, list[SourceChunk]],
    source_text: str,
) -> QuoteLocation | None:
    """Find the quote in one chunk of *section*; never join chunks."""

    matches: list[tuple[SourceChunk, QuoteLocation]] = []
    for chunk in chunks_by_section.get(section, []):
        location = locate_candidate(candidate, chunk=chunk, source_text=source_text)
        if location.status in {"verified_exact", "verified_normalized"}:
            matches.append((chunk, location))
    if len(matches) == 1:
        chunk, location = matches[0]
        return location.model_copy(
            update={
                "chunk_id": chunk.chunk_id,
                "locator": _locator_for(chunk),
                "resolved": True,
            }
        )
    if len(matches) > 1:
        return QuoteLocation(
            status="needs_review",
            reason="ambiguous_section",
            chunk_id=candidate.chunk_id,
            locator=f"§{section}",
        )
    return QuoteLocation(
        status="needs_review",
        reason="not_found_in_section",
        chunk_id=candidate.chunk_id,
        locator=f"§{section}",
    )


def _invalid(candidate: QuoteCandidate, reason: str) -> QuoteLocation:
    return QuoteLocation(
        status="rejected",
        reason=reason,
        chunk_id=candidate.chunk_id,
        locator=candidate.locator,
    )


def merge_audits(audits: list[QuoteAudit]) -> QuoteAudit:
    merged = QuoteAudit()
    for audit in audits:
        merged.total += audit.total
        merged.verified_exact += audit.verified_exact
        merged.verified_normalized += audit.verified_normalized
        merged.needs_review += audit.needs_review
        merged.rejected += audit.rejected
        merged.section_resolved += audit.section_resolved
        merged.reviews.extend(audit.reviews)
        for reason, count in audit.reasons.items():
            merged.reasons[reason] = merged.reasons.get(reason, 0) + count
    return merged
