"""Structural validation for formula and table evidence.

Free-text quotes are handled by ``evidence_locator``. Formulas and table rows
are different: the source text keeps subscripts and table layout in forms a
quote cannot match, and a string match cannot prove algebra or row/column
semantics.

This module therefore:

- requires a PaperMap element (equation/table) for the proposed ID;
- for a table, requires the row label and value (and variant/column when
  given) to appear together in one source chunk, then slices the excerpt from
  the source;
- for a formula, checks IDs, expression and symbol presence only. It never
  marks a formula ``verified_structured``; formulas go to manual review.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from content_studio.models import (
    EvidenceRecord,
    PaperElement,
    PaperMap,
    SourceChunk,
    StrictModel,
)
from content_studio.utils import normalize_quote, normalize_quote_with_map

StructuredStatus = Literal["verified_structured", "needs_review", "rejected"]
# A table row label and value that are further apart than this are probably
# not the same row; the span is a heuristic, so such evidence goes to review.
MAX_TABLE_ROW_SPAN = 120
_SECTION_NUMBER = re.compile(r"^§?\s*(\d+(?:\.\d+){0,2})")


class StructuredLocation(StrictModel):
    status: StructuredStatus
    reason: str = ""
    chunk_id: str = ""
    locator: str = ""
    excerpt: str = ""
    char_start: int = 0
    char_end: int = 0
    table_id: str = ""
    formula_id: str = ""
    column_label: str = ""
    verification_method: Literal["row_span", "cell_column", "manual"] = "manual"
    normalized_expression: str = ""
    normalization: str = ""


class StructuredReview(StrictModel):
    candidate_id: str
    kind: str
    status: StructuredStatus
    reason: str
    detail: str = ""
    source_id: str = ""
    chunk_id: str = ""
    locator: str = ""
    scope: str = ""
    verification_method: str = ""


class StructuredAudit(StrictModel):
    total: int = 0
    verified_structured: int = 0
    needs_review: int = 0
    rejected: int = 0
    reasons: dict[str, int] = Field(default_factory=dict)
    reviews: list[StructuredReview] = Field(default_factory=list)

    @property
    def accepted(self) -> int:
        return self.verified_structured


def _norm(value: str) -> str:
    return normalize_quote(value or "")


def normalize_formula(text: str) -> str:
    """Normalise notation for *matching only*, never for semantics.

    The result is recorded next to the original expression in the review
    record. A normalized match does not make a formula verified.
    """

    value = normalize_quote(text)
    value = value.replace("√", "sqrt")
    value = value.replace(chr(92) + "sqrt", "sqrt")
    value = value.replace(chr(92) + "text", "")
    value = value.replace(chr(92) + "mathrm", "")
    value = value.replace("^{", "^").replace("_{", "_")
    value = value.replace("{", "").replace("}", "").replace(chr(92), "")
    return value.replace(" ", "")


def _section_key(value: str) -> str:
    match = _SECTION_NUMBER.match(value.strip())
    if match:
        return match.group(1)
    return _norm(value)


def _find_element(
    paper_map: PaperMap | None,
    kind: Literal["formula", "table"],
    value: str,
    locator: str,
) -> PaperElement | None:
    if paper_map is None:
        return None
    element_kind = "equation" if kind == "formula" else "table"
    items = [element for element in paper_map.elements if element.kind == element_kind]
    if not items:
        return None
    if value:
        for element in items:
            if value == element.paper_item_id:
                return element
    needle = _norm(value or locator)
    if not needle:
        return None
    for element in items:
        blob = _norm(f"{element.title} {element.locator}")
        if needle in blob or blob in needle:
            return element
    return None


def _section_chunks(chunks: dict[str, SourceChunk], section: str) -> list[SourceChunk]:
    if not section:
        return sorted(chunks.values(), key=lambda chunk: chunk.index)
    key = _section_key(section)
    selected: list[SourceChunk] = []
    for chunk in chunks.values():
        label = _norm(chunk.section)
        if not label:
            continue
        if key and (label.startswith(key.lower()) or f" {key.lower()} " in f" {label} "):
            selected.append(chunk)
        elif key == label:
            selected.append(chunk)
    selected.sort(key=lambda chunk: chunk.index)
    if selected:
        return selected
    needle = _norm(section)
    return [
        chunk
        for chunk in sorted(chunks.values(), key=lambda item: item.index)
        if needle and needle in _norm(chunk.section)
    ]


def _span_between(
    source_text: str,
    chunk: SourceChunk,
    first: str,
    second: str,
) -> tuple[str, int, int] | None:
    chunk_text = source_text[chunk.char_start : chunk.char_end]
    normalized, index_map = normalize_quote_with_map(chunk_text)
    first_norm = _norm(first)
    second_norm = _norm(second)
    first_pos = normalized.find(first_norm)
    second_pos = normalized.find(second_norm)
    if first_pos < 0 or second_pos < 0:
        return None
    start_norm = min(first_pos, second_pos)
    end_norm = max(first_pos + len(first_norm), second_pos + len(second_norm))
    if end_norm <= start_norm:
        return None
    start = chunk.char_start + index_map[start_norm]
    end = chunk.char_start + index_map[end_norm - 1] + 1
    return source_text[start:end], start, end


def validate_structured_record(
    record: EvidenceRecord,
    *,
    paper_map: PaperMap | None,
    chunks: dict[str, SourceChunk],
    source_texts: dict[str, str],
) -> StructuredLocation:
    if record.evidence_type == "formula":
        return _validate_formula(record, paper_map, chunks, source_texts)
    if record.evidence_type == "table":
        return _validate_table(record, paper_map, chunks, source_texts)
    return StructuredLocation(status="needs_review", reason="not_structured_evidence")


def _validate_formula(
    record: EvidenceRecord,
    paper_map: PaperMap | None,
    chunks: dict[str, SourceChunk],
    source_texts: dict[str, str],
) -> StructuredLocation:
    formula = record.formula
    if formula is None:
        return StructuredLocation(status="needs_review", reason="missing_formula_fields")
    if paper_map is None:
        return StructuredLocation(
            status="needs_review", reason="no_paper_map", formula_id=formula.formula_id
        )
    element = _find_element(
        paper_map, "formula", formula.formula_id, formula.locator or record.locator
    )
    if element is None:
        return StructuredLocation(
            status="needs_review", reason="unknown_paper_element", formula_id=formula.formula_id
        )
    if not formula.expression.strip() or not formula.symbols:
        return StructuredLocation(
            status="needs_review",
            reason="missing_formula_fields",
            formula_id=element.paper_item_id,
        )
    section = element.locator or formula.locator or record.locator
    selected = _section_chunks(chunks, section)
    if not selected:
        return StructuredLocation(
            status="needs_review",
            reason="section_not_found",
            formula_id=element.paper_item_id,
            locator=f"§{section}" if section else "",
        )
    source_text = source_texts.get(record.source_id, "")
    section_text = normalize_formula(
        " ".join(source_text[chunk.char_start : chunk.char_end] for chunk in selected)
    )
    missing = [
        symbol for symbol in formula.symbols if normalize_formula(symbol) not in section_text
    ]
    # Prefer the substantive chunk over a heading-only chunk, so the human
    # reviewer sees the formula context rather than the section heading.
    chunk = max(selected, key=lambda item: item.text_chars)
    return StructuredLocation(
        status="needs_review",
        reason="formula_symbols_not_found" if missing else "formula_semantics_manual",
        chunk_id=chunk.chunk_id,
        locator=f"§{chunk.section}" if chunk.section else "",
        excerpt=source_text[chunk.char_start : chunk.char_end],
        formula_id=element.paper_item_id,
        verification_method="manual",
        normalized_expression=normalize_formula(formula.expression),
        normalization="unicode-math/v1",
    )


def _validate_table(
    record: EvidenceRecord,
    paper_map: PaperMap | None,
    chunks: dict[str, SourceChunk],
    source_texts: dict[str, str],
) -> StructuredLocation:
    table = record.table
    if table is None:
        return StructuredLocation(status="needs_review", reason="missing_table_fields")
    if paper_map is None:
        return StructuredLocation(
            status="needs_review", reason="no_paper_map", table_id=table.table_id
        )
    element = _find_element(paper_map, "table", table.table_id, table.locator or record.locator)
    if element is None:
        return StructuredLocation(
            status="needs_review", reason="unknown_paper_element", table_id=table.table_id
        )
    if table.scope == "prose":
        return StructuredLocation(
            status="needs_review",
            reason="prose_not_table_cell",
            table_id=element.paper_item_id,
            column_label=table.column_label,
            verification_method="manual",
        )
    if not table.row_label.strip() or not table.value.strip():
        return StructuredLocation(
            status="needs_review", reason="missing_table_fields", table_id=element.paper_item_id
        )
    section = element.locator or table.locator or record.locator
    selected = _section_chunks(chunks, section)
    if not selected:
        return StructuredLocation(
            status="needs_review",
            reason="section_not_found",
            table_id=element.paper_item_id,
            locator=f"§{section}" if section else "",
        )

    row_norm = _norm(table.row_label)
    value_norm = _norm(table.value)
    variant_norm = _norm(table.variant)
    column_norm = _norm(table.column_label)
    source_text = source_texts.get(record.source_id, "")
    matches: list[tuple[SourceChunk, str, int, int]] = []
    row_seen = False
    wide_span_seen = False
    for chunk in selected:
        chunk_text = source_text[chunk.char_start : chunk.char_end]
        normalized = _norm(chunk_text)
        row_here = row_norm in normalized
        value_here = value_norm in normalized
        row_seen = row_seen or row_here
        if not (row_here and value_here):
            continue
        if variant_norm and variant_norm not in normalized:
            continue
        if column_norm and column_norm not in normalized:
            continue
        span = _span_between(source_text, chunk, table.row_label, table.value)
        if span is None:
            continue
        if span[2] - span[1] > MAX_TABLE_ROW_SPAN:
            wide_span_seen = True
            continue
        matches.append((chunk, span[0], span[1], span[2]))

    if len(matches) > 1:
        return StructuredLocation(
            status="needs_review", reason="ambiguous_table_row", table_id=element.paper_item_id
        )
    if len(matches) == 1:
        chunk, excerpt, start, end = matches[0]
        # Row/label co-occurrence is not column semantics. Without a table
        # parser that maps the header to this cell, the candidate must stay in
        # human review; span checks are only an auxiliary constraint.
        return StructuredLocation(
            status="needs_review",
            reason="column_semantics_unverified",
            chunk_id=chunk.chunk_id,
            locator=f"§{chunk.section}" if chunk.section else "",
            excerpt=excerpt,
            char_start=start,
            char_end=end,
            table_id=element.paper_item_id,
            column_label=table.column_label,
            verification_method="row_span",
        )
    if wide_span_seen:
        return StructuredLocation(
            status="needs_review",
            reason="table_row_span_too_wide",
            table_id=element.paper_item_id,
        )
    if row_seen:
        return StructuredLocation(
            status="needs_review",
            reason="table_row_split_or_missing_value",
            table_id=element.paper_item_id,
        )
    return StructuredLocation(
        status="needs_review",
        reason="table_values_not_found",
        table_id=element.paper_item_id,
    )


def review_for(record: EvidenceRecord, location: StructuredLocation) -> StructuredReview:
    kind = "formula" if record.evidence_type == "formula" else "table"
    scope = record.table.scope if kind == "table" and record.table is not None else ""
    detail = ""
    if kind == "formula" and record.formula is not None:
        detail = (
            f"{record.formula.expression[:220]} | normalized: "
            f"{location.normalized_expression[:220]} | "
            f"rules: {location.normalization}"
        )
    elif kind == "table" and record.table is not None:
        detail = (
            f"{record.table.row_label} | {record.table.column_label} | "
            f"{record.table.value} {record.table.unit} {record.table.variant}"
        ).strip()
    return StructuredReview(
        candidate_id=record.evidence_id,
        kind=kind,
        status=location.status,
        reason=location.reason,
        detail=detail,
        source_id=record.source_id,
        chunk_id=location.chunk_id or record.chunk_id,
        locator=location.locator or record.locator,
        scope=scope,
        verification_method=location.verification_method,
    )


def merge_structured_audits(audits: list[StructuredAudit]) -> StructuredAudit:
    merged = StructuredAudit()
    for audit in audits:
        merged.total += audit.total
        merged.verified_structured += audit.verified_structured
        merged.needs_review += audit.needs_review
        merged.rejected += audit.rejected
        merged.reviews.extend(audit.reviews)
        for reason, count in audit.reasons.items():
            merged.reasons[reason] = merged.reasons.get(reason, 0) + count
    return merged
