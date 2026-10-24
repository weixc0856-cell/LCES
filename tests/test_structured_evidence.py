from __future__ import annotations

from content_studio.models import (
    EvidenceRecord,
    FormulaEvidence,
    PaperElement,
    PaperMap,
    SourceChunk,
    TableEvidence,
)
from content_studio.structured_evidence import (
    StructuredAudit,
    merge_structured_audits,
    normalize_formula,
    review_for,
    validate_structured_record,
)


def _chunks(segments: list[tuple[str, str]]):
    text_parts: list[str] = []
    chunks: dict[str, SourceChunk] = {}
    cursor = 0
    for index, (section, body) in enumerate(segments):
        if text_parts:
            cursor += 2
        start = cursor
        text_parts.append(body)
        cursor += len(body)
        chunk_id = f"source-001:b{index:04d}"
        chunks[chunk_id] = SourceChunk(
            chunk_id=chunk_id,
            index=index,
            section=section,
            char_start=start,
            char_end=cursor,
            text_chars=len(body),
        )
    return "\n\n".join(text_parts), chunks


def _paper_map() -> PaperMap:
    return PaperMap(
        project_id="demo",
        elements=[
            PaperElement(
                paper_item_id="paper-001",
                kind="table",
                title="Table 2: BLEU results",
                locator="§6.1 Table 2",
            ),
            PaperElement(
                paper_item_id="paper-002",
                kind="equation",
                title="Scaled attention formula",
                locator="§3.2.1 公式",
            ),
        ],
    )


def _record(evidence_type: str, **overrides) -> EvidenceRecord:
    values = {
        "evidence_id": "evidence-001",
        "source_id": "source-001",
        "chunk_id": "source-001:b0000",
        "claim_id": "claim-001",
        "evidence_type": evidence_type,
        "support_relation": "supports",
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def _table(**overrides) -> TableEvidence:
    values = {
        "table_id": "Table 2",
        "row_label": "Transformer (base model)",
        "column_label": "EN-DE",
        "value": "27.3",
        "variant": "base",
        "locator": "§6.1",
    }
    values.update(overrides)
    return TableEvidence(**values)


def test_table_row_is_verified_when_label_and_value_share_a_chunk():
    text, chunks = _chunks(
        [
            ("6.1 Machine Translation", "Transformer (base model) 27.3 38.1 EN-DE"),
            ("3.2.1 Scaled Dot-Product Attention", "softmax QK d_k"),
        ]
    )
    record = _record("table", table=_table())

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    # Row co-occurrence alone is not column semantics: without a table parser
    # that maps the header to this cell, the candidate stays in review.
    assert location.status == "needs_review"
    assert location.reason == "column_semantics_unverified"
    assert location.table_id == "paper-001"
    assert "Transformer (base model)" in location.excerpt
    assert "27.3" in location.excerpt
    assert location.locator == "§6.1 Machine Translation"
    assert location.verification_method == "row_span"


def test_table_with_missing_value_is_not_verified():
    text, chunks = _chunks(
        [("6.1 Machine Translation", "Transformer (base model) 27.3 38.1 EN-DE")]
    )
    record = _record("table", table=_table(value="99.9"))

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason in {
        "table_values_not_found",
        "table_row_split_or_missing_value",
    }


def test_table_row_split_across_chunks_is_not_verified():
    text, chunks = _chunks(
        [
            ("6.1 Machine Translation", "Transformer (base model) EN-DE"),
            ("6.1 Machine Translation", "27.3 38.1"),
        ]
    )
    record = _record("table", table=_table())

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "table_row_split_or_missing_value"


def test_wide_table_span_is_not_verified():
    filler = "x" * 200
    text, chunks = _chunks([("6.1 Machine Translation", f"base {filler} 25.8 EN-DE")])
    record = _record(
        "table",
        table=_table(row_label="base", value="25.8", variant="base"),
    )

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "table_row_span_too_wide"


def test_prose_scope_is_not_cell_evidence():
    text, chunks = _chunks(
        [("6.1 Machine Translation", "Transformer (base model) 27.3 38.1 EN-DE")]
    )
    record = _record("table", table=_table(scope="prose"))

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "prose_not_table_cell"


def test_unknown_table_id_is_not_verified():
    text, chunks = _chunks([("6.1 Machine Translation", "Transformer (base model) 27.3")])
    record = _record("table", table=_table(table_id="paper-999"))

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "unknown_paper_element"


def test_no_paper_map_blocks_structured_verification():
    text, chunks = _chunks([("6.1 Machine Translation", "Transformer (base model) 27.3")])
    record = _record("table", table=_table())

    location = validate_structured_record(
        record,
        paper_map=None,
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "no_paper_map"


def test_formula_is_always_manual_review():
    text, chunks = _chunks([("3.2.1 Scaled Dot-Product Attention", "softmax(QK^T/sqrt(d_k))V")])
    record = _record(
        "formula",
        chunk_id="source-001:b0000",
        formula=FormulaEvidence(
            formula_id="paper-002",
            expression="softmax(QK^T/sqrt(d_k))V",
            symbols=["softmax", "d_k"],
            locator="§3.2.1",
        ),
    )

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "formula_semantics_manual"
    assert location.formula_id == "paper-002"


def test_formula_normalisation_matches_notation_but_stays_manual():
    text, chunks = _chunks(
        [
            (
                "3.2.1 Scaled Dot-Product Attention",
                "softmax(QK^{T}/" + chr(92) + "sqrt{d_{k}})V",
            )
        ]
    )
    record = _record(
        "formula",
        formula=FormulaEvidence(
            formula_id="paper-002",
            expression="softmax(QK^T/√d_k)V",
            symbols=["softmax", "d_k"],
            locator="§3.2.1",
        ),
    )

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "formula_semantics_manual"
    assert location.normalized_expression
    assert location.normalization == "unicode-math/v1"
    assert location.verification_method == "manual"


def test_formula_original_expression_is_preserved_and_not_promoted():
    text, chunks = _chunks(
        [
            (
                "3.2.1 Scaled Dot-Product Attention",
                "softmax(QK^{T}/" + chr(92) + "sqrt{d_{k}})V",
            )
        ]
    )
    expression = "softmax(QK^T/√d_k)V"
    record = _record(
        "formula",
        formula=FormulaEvidence(
            formula_id="paper-002",
            expression=expression,
            symbols=["softmax", "d_k"],
            locator="§3.2.1",
        ),
    )

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert record.formula is not None
    assert record.formula.expression == expression
    assert location.normalized_expression
    assert location.normalized_expression != expression
    assert location.status == "needs_review"
    assert location.reason == "formula_semantics_manual"


def test_formula_normalisation_does_not_merge_different_symbols():
    text, chunks = _chunks([("3.2.1 Scaled Dot-Product Attention", "softmax d_v")])
    record = _record(
        "formula",
        formula=FormulaEvidence(
            formula_id="paper-002",
            expression="softmax(d_k)V",
            symbols=["softmax", "d_k"],
            locator="§3.2.1",
        ),
    )

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "formula_symbols_not_found"


def test_normalize_formula_unicode_equivalence_is_for_matching_only():
    assert normalize_formula("√d_k") == normalize_formula(chr(92) + "sqrt{d_{k}}")
    assert normalize_formula("d_k") != normalize_formula("d_v")


def test_formula_symbols_missing_is_reported():
    text, chunks = _chunks([("3.2.1 Scaled Dot-Product Attention", "softmax only")])
    record = _record(
        "formula",
        formula=FormulaEvidence(
            formula_id="paper-002",
            expression="softmax(QK^T/sqrt(d_k))V",
            symbols=["softmax", "d_k"],
            locator="§3.2.1",
        ),
    )

    location = validate_structured_record(
        record,
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )

    assert location.status == "needs_review"
    assert location.reason == "formula_symbols_not_found"


def test_structured_audit_merges_and_reviews_carry_detail():
    text, chunks = _chunks([("6.1 Machine Translation", "Transformer (base model) 27.3")])
    location = validate_structured_record(
        _record("table", table=_table(value="99.9")),
        paper_map=_paper_map(),
        chunks=chunks,
        source_texts={"source-001": text},
    )
    review = review_for(_record("table", table=_table(value="99.9")), location)

    audit = StructuredAudit(
        total=1,
        needs_review=1,
        reasons={location.reason: 1},
        reviews=[review],
    )
    merged = merge_structured_audits([audit, audit])

    assert merged.total == 2
    assert merged.needs_review == 2
    assert len(merged.reviews) == 2
    assert merged.reviews[0].kind == "table"
    assert "27.3" not in merged.reviews[0].detail
    assert merged.reviews[0].source_id == "source-001"
    assert merged.reviews[0].chunk_id == "source-001:b0000"
    assert merged.reviews[0].verification_method == "manual"
