"""Human review records for structured evidence.

Program checks can locate a table row or a formula, but they cannot sign a
fact. This module stores the review record, validates the linkage to the
project's sources/chunks/claims/paper map, and writes a reviewer decision
atomically with an appended audit entry.

A source conflict is data, not something to resolve automatically. A ``pass``
on a conflicted item requires an explicit acknowledgement; the sources and
locators stay in the record.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from content_studio.errors import ValidationFailure
from content_studio.evidence import load_claims
from content_studio.ingestion import load_registry
from content_studio.models import StrictModel
from content_studio.planning import load_paper_map
from content_studio.source_map import load_source_map
from content_studio.utils import utc_now, write_json_atomic

ReviewConclusion = Literal["pending", "pass", "fail", "needs_revision", "blocked"]
ConflictStatus = Literal["none", "source_conflict", "unresolved"]
ResearchFindingKind = Literal[
    "verified",
    "needs_review",
    "source_conflict",
    "incorrect",
    "not_verifiable",
]
EvidenceKind = Literal["table", "formula"]
SubstantiveScope = Literal["source_transcription", "claim_interpretation", "course_usage"]
SubstantiveFinding = Literal["consistent", "inconsistent", "partial", "not_assessed"]
REVIEW_CONCLUSIONS = ("pass", "fail", "needs_revision", "blocked")
SUBSTANTIVE_FINDINGS = ("consistent", "inconsistent", "partial", "not_assessed")
SUBSTANTIVE_SCOPES = ("source_transcription", "claim_interpretation", "course_usage")


class ResearchSource(StrictModel):
    source_id: str = Field(min_length=1)
    url: str = ""
    locator: str = ""


class ResearchVerification(StrictModel):
    """An external-source check, separate from a formal human signature.

    ``research_finding=verified`` means the formula/table source was checked
    against an authoritative source. It is not a human signature and never
    changes ``reviewed_by_human`` or the review conclusion automatically.
    """

    claim_id: str = ""
    paper_id: str = ""
    formula_id: str = ""
    research_finding: ResearchFindingKind = "needs_review"
    details: str = ""
    source_url: str = ""
    source_version: str = ""
    source_locator: str = ""
    transcribed_expression: str = ""
    symbol_definitions: dict[str, str] = Field(default_factory=dict)
    dimension_check: str = ""
    derivation_check: str = ""
    limitations: str = ""
    sources: list[ResearchSource] = Field(default_factory=list)
    verified_at: date | None = None
    reviewed_by_human: bool = False
    formal_review_status: ReviewConclusion = "pending"


class SubstantiveReview(StrictModel):
    """An AI substantive review, stored next to the human decision.

    The record is deliberately a different type from the review conclusion.
    It can say a transcription or claim interpretation is consistent, but it
    carries ``reviewer_kind=ai`` and no ``reviewed_by_human`` flag, so it can
    never be read as, or promoted to, a human signature.
    """

    reviewer: str = Field(min_length=1)
    reviewer_kind: Literal["ai"] = "ai"
    reviewed_at: datetime
    finding: SubstantiveFinding
    scopes: list[SubstantiveScope] = Field(min_length=1)
    basis: str = Field(min_length=1)
    limitations: str = ""


class ReviewItem(StrictModel):
    review_id: str = Field(pattern=r"^review-[a-z0-9.-]+$")
    local_evidence_id: str
    window: str
    paper_id: str = ""
    source_id: str
    chunk_id: str
    locator: str
    evidence_kind: EvidenceKind
    claim_id: str = ""
    claim_ref: str = ""
    claim: str = Field(min_length=1)
    program_status: str = ""
    program_reason: str = ""
    program_precheck: str = ""
    research_verification: list[ResearchVerification] = Field(default_factory=list)
    substantive_review: SubstantiveReview | None = None
    conflict_status: ConflictStatus = "none"
    conflict_acknowledged: bool = False
    reviewer: str = ""
    reviewed_at: datetime | None = None
    conclusion: ReviewConclusion = "pending"
    basis: str = ""
    missing: str = ""

    @model_validator(mode="after")
    def _signed_items_are_complete(self) -> ReviewItem:
        if self.conclusion != "pending":
            if not self.reviewer.strip():
                raise ValueError("reviewer is required once a conclusion is recorded")
            if self.reviewed_at is None:
                raise ValueError("reviewed_at is required once a conclusion is recorded")
            if not self.basis.strip():
                raise ValueError("basis is required once a conclusion is recorded")
        if self.conflict_status != "none" and self.conclusion == "pass":
            if not self.conflict_acknowledged:
                raise ValueError("a source conflict must be acknowledged before it can pass")
        if self.conflict_status == "none" and any(
            finding.research_finding == "source_conflict" for finding in self.research_verification
        ):
            raise ValueError(
                "research verification reports a source conflict but conflict_status is none"
            )
        return self


class ReviewDocument(StrictModel):
    schema_version: str = "1.0"
    project_id: str
    status: str = "pending_human_review"
    note: str = ""
    items: list[ReviewItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_review_ids(self) -> ReviewDocument:
        identifiers = [item.review_id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("review_id values must be unique")
        return self


def default_review_path(project_dir: Path) -> Path:
    return project_dir / "internal" / "qa" / "structured_evidence_review.json"


def load_review(path: Path) -> ReviewDocument:
    if not path.is_file():
        raise ValidationFailure(f"structured evidence review file not found: {path}")
    try:
        return ReviewDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValidationFailure(f"invalid review file {path}: {exc}") from exc


def _validate_links(project_dir: Path, item: ReviewItem) -> None:
    registry = load_registry(project_dir)
    if registry is None:
        raise ValidationFailure("source registry is missing; cannot link the review record")
    source_ids = {source.source_id for source in registry.sources}
    if item.source_id not in source_ids:
        raise ValidationFailure(f"unknown source_id in review record: {item.source_id}")

    source_map = load_source_map(project_dir)
    if source_map is None:
        raise ValidationFailure("source map is missing; cannot verify the review chunk")
    chunks = {
        chunk.chunk_id: chunk for document in source_map.documents for chunk in document.chunks
    }
    chunk = chunks.get(item.chunk_id)
    if chunk is None:
        raise ValidationFailure(f"unknown chunk_id in review record: {item.chunk_id}")
    if not item.chunk_id.startswith(f"{item.source_id}:"):
        raise ValidationFailure(f"chunk {item.chunk_id} does not belong to source {item.source_id}")

    if item.claim_id:
        claims = load_claims(project_dir)
        if claims is None:
            raise ValidationFailure("claims.json is missing; cannot link claim_id")
        if item.claim_id not in {claim.claim_id for claim in claims}:
            raise ValidationFailure(f"unknown claim_id in review record: {item.claim_id}")
    elif not item.claim_ref.strip():
        raise ValidationFailure(
            "review record needs claim_id or claim_ref; unlinked evidence cannot be signed"
        )

    if item.paper_id:
        paper_map = load_paper_map(project_dir)
        if paper_map is None:
            raise ValidationFailure("paper map is missing; cannot link paper_id")
        if item.paper_id not in {element.paper_item_id for element in paper_map.elements}:
            raise ValidationFailure(f"unknown paper_id in review record: {item.paper_id}")


def validate_review_links(project_dir: Path, document: ReviewDocument) -> None:
    """Read-only check that every review item links to project data."""

    for item in document.items:
        _validate_links(project_dir, item)


def _append_audit(project_dir: Path, payload: dict[str, object]) -> Path:
    path = project_dir / "internal" / "qa" / "evidence_review_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return path


def record_review(
    project_dir: Path,
    review_id: str,
    reviewer: str,
    conclusion: str,
    basis: str,
    *,
    missing: str = "",
    conflict_ack: bool = False,
    review_path: Path | None = None,
) -> ReviewItem:
    """Record one human decision and append an audit entry."""

    if conclusion not in REVIEW_CONCLUSIONS:
        raise ValidationFailure(
            f"unknown conclusion '{conclusion}'; choose from {', '.join(REVIEW_CONCLUSIONS)}"
        )
    if not reviewer.strip():
        raise ValidationFailure("reviewer is required; anonymous reviews are not accepted")
    if not basis.strip():
        raise ValidationFailure("basis is required; a conclusion without evidence is not accepted")

    path = review_path or default_review_path(project_dir)
    document = load_review(path)
    item = next((entry for entry in document.items if entry.review_id == review_id), None)
    if item is None:
        raise ValidationFailure(f"review_id not found: {review_id}")
    if item.conflict_status != "none" and conclusion == "pass" and not conflict_ack:
        raise ValidationFailure("source conflict not acknowledged; pass requires --conflict-ack")
    _validate_links(project_dir, item)

    updated = item.model_copy(
        update={
            "reviewer": reviewer.strip(),
            "reviewed_at": utc_now(),
            "conclusion": conclusion,
            "basis": basis.strip(),
            "missing": missing.strip(),
            "conflict_acknowledged": item.conflict_acknowledged or conflict_ack,
        }
    )
    document = document.model_copy(
        update={
            "status": (
                "complete"
                if all(entry.conclusion != "pending" for entry in document.items)
                else "in_review"
            ),
            "items": [
                updated if entry.review_id == review_id else entry for entry in document.items
            ],
        }
    )
    write_json_atomic(path, document)

    _append_audit(
        project_dir,
        {
            "recorded_at": utc_now().isoformat(),
            "review_file": str(path.relative_to(project_dir)),
            "review_id": review_id,
            "previous_conclusion": item.conclusion,
            "conclusion": conclusion,
            "reviewer": reviewer.strip(),
            "basis": basis.strip(),
            "missing": missing.strip(),
            "conflict_status": item.conflict_status,
            "conflict_acknowledged": updated.conflict_acknowledged,
        },
    )
    # Re-read after the atomic replace so the caller sees exactly what is on disk.
    reloaded = load_review(path)
    return next(entry for entry in reloaded.items if entry.review_id == review_id)


def record_substantive_review(
    project_dir: Path,
    review_id: str,
    reviewer: str,
    finding: str,
    scopes: list[str],
    basis: str,
    *,
    limitations: str = "",
    review_path: Path | None = None,
) -> ReviewItem:
    """Record an AI substantive review without touching the human decision.

    The command exists so "an AI read this against the source" can be stored
    and audited separately from "a human signed this". It refuses to write a
    conclusion, a reviewer signature or a ``reviewed_by_human`` flag.
    """

    if not reviewer.strip():
        raise ValidationFailure("reviewer is required for a substantive review")
    if not basis.strip():
        raise ValidationFailure("basis is required; an unexplained finding is not accepted")
    if finding not in SUBSTANTIVE_FINDINGS:
        raise ValidationFailure(
            f"unknown finding '{finding}'; choose from {', '.join(SUBSTANTIVE_FINDINGS)}"
        )
    unknown = [scope for scope in scopes if scope not in SUBSTANTIVE_SCOPES]
    if not scopes or unknown:
        raise ValidationFailure(
            f"scope must be a non-empty subset of {', '.join(SUBSTANTIVE_SCOPES)}"
        )

    path = review_path or default_review_path(project_dir)
    document = load_review(path)
    item = next((entry for entry in document.items if entry.review_id == review_id), None)
    if item is None:
        raise ValidationFailure(f"review_id not found: {review_id}")
    _validate_links(project_dir, item)

    record = SubstantiveReview(
        reviewer=reviewer.strip(),
        reviewed_at=utc_now(),
        finding=finding,  # type: ignore[arg-type]
        scopes=scopes,  # type: ignore[arg-type]
        basis=basis.strip(),
        limitations=limitations.strip(),
    )
    updated = item.model_copy(update={"substantive_review": record})
    document = document.model_copy(
        update={
            "items": [
                updated if entry.review_id == review_id else entry for entry in document.items
            ]
        }
    )
    write_json_atomic(path, document)
    _append_audit(
        project_dir,
        {
            "recorded_at": utc_now().isoformat(),
            "layer": "ai_substantive_review",
            "review_file": str(path.relative_to(project_dir)),
            "review_id": review_id,
            "reviewer": record.reviewer,
            "reviewer_kind": record.reviewer_kind,
            "finding": record.finding,
            "scopes": record.scopes,
            "basis": record.basis,
            "limitations": record.limitations,
            "conclusion_unchanged": item.conclusion,
        },
    )
    reloaded = load_review(path)
    return next(entry for entry in reloaded.items if entry.review_id == review_id)


def unsigned_items(document: ReviewDocument) -> list[ReviewItem]:
    """Items still missing a completed human conclusion."""

    return [item for item in document.items if item.conclusion != "pass"]


def unacknowledged_conflicts(document: ReviewDocument) -> list[ReviewItem]:
    """Items whose source conflict was never explicitly acknowledged."""

    return [
        item
        for item in document.items
        if item.conflict_status != "none" and not item.conflict_acknowledged
    ]
