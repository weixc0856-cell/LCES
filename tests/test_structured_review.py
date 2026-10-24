from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.errors import ValidationFailure
from content_studio.models import (
    Claim,
    PaperElement,
    PaperMap,
    SourceChunk,
    SourceDocumentMap,
    SourceMap,
    SourceRecord,
    SourceRegistry,
)
from content_studio.structured_review import (
    ReviewDocument,
    ReviewItem,
    record_review,
)
from content_studio.utils import write_json

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "design"
    / "structured-evidence-review-2026-10-24.json"
)


def _item(**overrides) -> ReviewItem:
    values = {
        "review_id": "review-test",
        "local_evidence_id": "evidence-001",
        "window": "B_results",
        "paper_id": "paper-001",
        "source_id": "source-001",
        "chunk_id": "source-001:b0000",
        "locator": "§6.1",
        "evidence_kind": "table",
        "claim_id": "claim-001",
        "claim": "A table claim",
        "program_status": "needs_review",
        "program_reason": "column_semantics_unverified",
    }
    values.update(overrides)
    return ReviewItem(**values)


def test_template_keeps_research_and_human_status_separate():
    document = ReviewDocument.model_validate_json(TEMPLATE.read_text(encoding="utf-8"))

    assert len(document.items) == 7
    assert document.status == "pending_human_review"
    assert all(item.conclusion == "pending" for item in document.items)
    assert all(
        verification.reviewed_by_human is False
        for item in document.items
        for verification in item.research_verification
    )
    assert all(
        verification.formal_review_status == "pending"
        for item in document.items
        for verification in item.research_verification
    )

    conflict = next(
        item for item in document.items if item.review_id == "review-table2-big-enfr-conflict"
    )
    assert conflict.conflict_status == "source_conflict"
    finding = conflict.research_verification[0]
    assert finding.research_finding == "source_conflict"
    assert "41.0" in finding.details and "41.8" in finding.details
    assert {source.source_id for source in finding.sources} == {
        "neurips-2017-original",
        "arxiv-1706.03762",
    }

    formula = next(item for item in document.items if item.review_id == "review-formula-attention")
    verification = formula.research_verification[0]
    assert verification.research_finding == "verified"
    assert verification.transcribed_expression
    assert verification.symbol_definitions["d_k"]
    assert verification.dimension_check
    assert verification.derivation_check
    assert verification.reviewed_by_human is False


def test_a_signed_item_requires_reviewer_date_and_basis():
    with pytest.raises(ValidationError, match="reviewer"):
        _item(conclusion="pass")
    with pytest.raises(ValidationError, match="reviewed_at"):
        _item(conclusion="pass", reviewer="reviewer")
    with pytest.raises(ValidationError, match="basis"):
        _item(conclusion="pass", reviewer="reviewer", reviewed_at="2026-10-24T00:00:00Z")


def test_conflict_pass_requires_explicit_acknowledgement():
    signed = {
        "conclusion": "pass",
        "reviewer": "reviewer",
        "reviewed_at": "2026-10-24T00:00:00Z",
        "basis": "used Table 2 value",
        "conflict_status": "source_conflict",
    }
    with pytest.raises(ValidationError, match="acknowledged"):
        _item(**signed)

    item = _item(**signed, conflict_acknowledged=True)
    assert item.conflict_acknowledged is True


def test_source_conflict_finding_requires_conflict_status():
    with pytest.raises(ValidationError, match="conflict_status"):
        _item(
            research_verification=[
                {
                    "research_finding": "source_conflict",
                    "details": "41.0 vs 41.8",
                }
            ]
        )


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "internal").mkdir(parents=True)
    (root / "project.yaml").write_text(
        "project_id: demo" + chr(10) + "title: Structured review" + chr(10),
        encoding="utf-8",
    )
    (root / "internal" / "plan").mkdir(parents=True)
    (root / "internal" / "qa").mkdir(parents=True)
    registry = SourceRegistry(
        project_id="demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Paper",
                kind="markdown",
                origin="input/paper.md",
            )
        ],
    )
    chunk = SourceChunk(
        chunk_id="source-001:b0000",
        index=0,
        section="6.1",
        char_start=0,
        char_end=10,
        text_chars=10,
    )
    source_map = SourceMap(
        project_id="demo",
        documents=[
            SourceDocumentMap(
                source_id="source-001",
                text_chars=10,
                chunks=[chunk],
            )
        ],
    )
    paper_map = PaperMap(
        project_id="demo",
        elements=[
            PaperElement(
                paper_item_id="paper-001",
                kind="table",
                title="Table 2",
                locator="§6.1",
            )
        ],
    )
    write_json(root / "internal" / "source_registry.json", registry)
    write_json(root / "internal" / "source_map.json", source_map)
    write_json(
        root / "internal" / "claims.json",
        [Claim(claim_id="claim-001", statement="A claim", claim_type="fact")],
    )
    write_json(root / "internal" / "plan" / "paper_map.json", paper_map)
    write_json(
        root / "internal" / "qa" / "structured_evidence_review.json",
        ReviewDocument(project_id="demo", items=[_item()]),
    )
    return root


def test_record_review_updates_json_and_audit(tmp_path: Path):
    root = _project(tmp_path)

    updated = record_review(
        root,
        "review-test",
        "Reviewer",
        "pass",
        "Checked Table 2 on the original PDF.",
    )

    assert updated.conclusion == "pass"
    assert updated.reviewer == "Reviewer"
    assert updated.reviewed_at is not None
    stored = ReviewDocument.model_validate_json(
        (root / "internal" / "qa" / "structured_evidence_review.json").read_text(encoding="utf-8")
    )
    assert stored.items[0].conclusion == "pass"
    audit = (
        (root / "internal" / "qa" / "evidence_review_audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(audit) == 1
    entry = json.loads(audit[0])
    assert entry["review_id"] == "review-test"
    assert entry["conclusion"] == "pass"
    assert entry["reviewer"] == "Reviewer"


def test_record_review_rejects_missing_fields_and_unknown_ids(tmp_path: Path):
    root = _project(tmp_path)

    with pytest.raises(ValidationFailure, match="unknown conclusion"):
        record_review(root, "review-test", "Reviewer", "pending", "basis")
    with pytest.raises(ValidationFailure, match="reviewer is required"):
        record_review(root, "review-test", "  ", "pass", "basis")
    with pytest.raises(ValidationFailure, match="basis is required"):
        record_review(root, "review-test", "Reviewer", "pass", "  ")
    with pytest.raises(ValidationFailure, match="review_id not found"):
        record_review(root, "review-missing", "Reviewer", "pass", "basis")


def test_record_review_rejects_conflict_pass_without_ack(tmp_path: Path):
    root = _project(tmp_path)
    document = ReviewDocument(
        project_id="demo",
        items=[
            _item(
                conflict_status="source_conflict",
                research_verification=[
                    {"research_finding": "source_conflict", "details": "41.0 vs 41.8"}
                ],
            )
        ],
    )
    write_json(root / "internal" / "qa" / "structured_evidence_review.json", document)

    with pytest.raises(ValidationFailure, match="conflict not acknowledged"):
        record_review(root, "review-test", "Reviewer", "pass", "used Table 2 value")

    updated = record_review(
        root,
        "review-test",
        "Reviewer",
        "pass",
        "used Table 2 value; conflict acknowledged",
        conflict_ack=True,
    )
    assert updated.conflict_acknowledged is True
    assert updated.research_verification[0].sources == []


def test_cli_review_evidence_records_a_decision(tmp_path: Path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "review-evidence",
            str(root),
            "--review-id",
            "review-test",
            "--by",
            "Reviewer",
            "--conclusion",
            "pass",
            "--basis",
            "Checked Table 2 on the original PDF.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "review-test" in result.output
    stored = ReviewDocument.model_validate_json(
        (root / "internal" / "qa" / "structured_evidence_review.json").read_text(encoding="utf-8")
    )
    assert stored.items[0].conclusion == "pass"
    assert stored.items[0].reviewer == "Reviewer"


def test_record_review_rejects_broken_links(tmp_path: Path):
    root = _project(tmp_path)
    document = ReviewDocument(
        project_id="demo",
        items=[_item(claim_id="claim-999")],
    )
    write_json(root / "internal" / "qa" / "structured_evidence_review.json", document)
    with pytest.raises(ValidationFailure, match="unknown claim_id"):
        record_review(root, "review-test", "Reviewer", "needs_revision", "claim missing")

    document = ReviewDocument(
        project_id="demo",
        items=[_item(chunk_id="source-001:b9999")],
    )
    write_json(root / "internal" / "qa" / "structured_evidence_review.json", document)
    with pytest.raises(ValidationFailure, match="unknown chunk_id"):
        record_review(root, "review-test", "Reviewer", "needs_revision", "chunk missing")
