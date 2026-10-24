"""Unified data contracts.

These models are the single source of truth for JSON Schemas (see
``lces export-schemas``). The public content model is deliberately separate
from the internal speaker script: no template may read narration fields, and
``extra="forbid"`` keeps internal fields from leaking into public data.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from content_studio.utils import utc_now

ContentMode = Literal[
    "paper_course",
    "research_report",
    "news_commentary",
    "engineering_tutorial",
    "series_course",
    "quick_brief",
]

TaskStatus = Literal[
    "CREATED",
    "INGESTING",
    "RESEARCHING",
    "PLANNING",
    "GENERATING",
    "VALIDATING",
    "REVIEW_REQUIRED",
    "RELEASED",
    "FAILED",
    "NEEDS_REVISION",
]

SourceKind = Literal["web", "pdf", "markdown", "text", "html", "docx"]
AccessStatus = Literal["fetched", "partial", "unavailable"]
ClaimType = Literal[
    "fact", "inference", "assumption", "prediction", "opinion", "unknown", "disputed"
]
Importance = Literal["key", "supporting"]
SupportRelation = Literal["supports", "refutes", "partially_supports", "background"]
# Canonical review states plus the legacy values already present in older
# projects. `evidence.canonical_status()` maps the legacy ones.
VerificationStatus = Literal[
    "pending",
    "supported",
    "partially_supported",
    "contradicted",
    "insufficient_evidence",
    "not_applicable",
    "unverified",
    "verified",
    "conflict",
    "unverifiable",
]
EvidenceType = Literal[
    "quote",
    "data",
    "figure",
    "table",
    "formula",
    "experiment",
    "official_statement",
    "analysis",
]
CheckStatus = Literal["pass", "fail", "warn", "not_run"]
GateId = Literal["gate_1_research", "gate_2_content", "gate_3_engineering", "gate_4_release"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    title: str = Field(min_length=1)
    content_mode: ContentMode = "paper_course"
    language: str = "zh-CN"
    audience: str = "具备技术背景的学习者"
    input_paths: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    target_duration_minutes: int = Field(default=20, ge=1, le=240)
    release_requires_human_approval: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class SourceRecord(StrictModel):
    source_id: str = Field(pattern=r"^source-[0-9]{3,}$")
    title: str = Field(min_length=1)
    kind: SourceKind
    origin: str
    local_path: str | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    publisher: str | None = None
    published_at: str | None = None
    access_status: AccessStatus = "fetched"
    text_chars: int = Field(default=0, ge=0)
    notes: str | None = None


class SourceRegistry(StrictModel):
    project_id: str
    created_at: datetime = Field(default_factory=utc_now)
    sources: list[SourceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_source_ids(self) -> SourceRegistry:
        identifiers = [item.source_id for item in self.sources]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("source_id values must be unique")
        return self


class SourceChunk(StrictModel):
    """One contiguous slice of a stored source text.

    Chunks tile the whole text with no gaps and no overlap, so sectioned
    research can cover every character without a head-truncation budget.
    """

    chunk_id: str = Field(pattern=r"^source-[0-9]{3,}:b[0-9]{4,}$")
    index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    section: str = ""
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    text_chars: int = Field(gt=0)

    @model_validator(mode="after")
    def _length_matches_offsets(self) -> SourceChunk:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if self.text_chars != self.char_end - self.char_start:
            raise ValueError("text_chars must equal char_end - char_start")
        return self


class SourceDocumentMap(StrictModel):
    source_id: str = Field(pattern=r"^source-[0-9]{3,}$")
    sha256: str = Field(default="", pattern=r"^(|[0-9a-f]{64})$")
    parser: str = ""
    text_chars: int = Field(gt=0)
    chunks: list[SourceChunk] = Field(min_length=1)

    @model_validator(mode="after")
    def _chunks_tile_the_text(self) -> SourceDocumentMap:
        previous_end = 0
        for expected_index, chunk in enumerate(self.chunks):
            if chunk.index != expected_index:
                raise ValueError(
                    f"chunk index {chunk.index} out of order; expected {expected_index}"
                )
            if chunk.char_start != previous_end:
                raise ValueError(
                    f"chunk {chunk.chunk_id} starts at {chunk.char_start}, expected {previous_end}"
                )
            previous_end = chunk.char_end
        if previous_end != self.text_chars:
            raise ValueError(
                f"chunks cover {previous_end} characters, document has {self.text_chars}"
            )
        return self


class SourceMap(StrictModel):
    """Page/section/chunk map for every ingested source."""

    project_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    documents: list[SourceDocumentMap] = Field(default_factory=list)


class Claim(StrictModel):
    claim_id: str = Field(pattern=r"^claim-[0-9]{3,}$")
    statement: str = Field(min_length=1)
    claim_type: ClaimType
    importance: Importance = "supporting"
    # Review state is owned by a human reviewer (`lces review-claims`), never
    # by the model that produced the claim.
    verification_status: VerificationStatus = "pending"
    reviewer: str = ""
    reviewed_at: datetime | None = None
    notes: str = ""


class FormulaEvidence(StrictModel):
    """A formula proposed as evidence.

    The program can check the paper element, locator and symbol presence. It
    cannot prove the algebra, so a formula never becomes ``verified_exact``.
    """

    formula_id: str = ""
    expression: str = ""
    symbols: list[str] = Field(default_factory=list)
    locator: str = ""


class TableEvidence(StrictModel):
    """One table cell/row proposed as evidence."""

    # prose is a table-related sentence, not a cell; the validator keeps it
    # out of cell evidence.
    scope: Literal["cell", "row", "prose"] = "row"
    table_id: str = ""
    row_label: str = ""
    column_label: str = ""
    value: str = ""
    unit: str = ""
    variant: str = ""
    locator: str = ""


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(pattern=r"^evidence-[0-9]{3,}$")
    source_id: str
    # The exact chunk the candidate was taken from. The locator refuses to
    # search other chunks, so a quote can never be assembled across chunks.
    # The value is checked against the window map, not a regex: an invalid ID
    # becomes a review/rejection reason instead of failing the whole response.
    chunk_id: str = ""
    claim_id: str
    evidence_type: EvidenceType
    locator: str = ""
    source_excerpt: str = Field(default="", max_length=2000)
    support_relation: SupportRelation
    verification_status: VerificationStatus = "unverified"
    # Set by the deterministic locator, never by the model.
    quote_status: Literal[
        "unverified",
        "verified_exact",
        "verified_normalized",
        "verified_structured",
    ] = "unverified"
    formula: FormulaEvidence | None = None
    table: TableEvidence | None = None
    reviewer: str = ""
    checked_at: datetime | None = None
    notes: str = ""


class EvidenceLedger(StrictModel):
    project_id: str
    records: list[EvidenceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_evidence_ids(self) -> EvidenceLedger:
        identifiers = [item.evidence_id for item in self.records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence_id values must be unique")
        return self


class ResearchFinding(StrictModel):
    claim_id: str
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    limitations: str = ""


class ResearchAnalysis(StrictModel):
    """Structured model output for the research stage."""

    research_question: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    source_conflicts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ResearchBrief(StrictModel):
    project_id: str
    research_question: str
    scope: str
    findings: list[ResearchFinding] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    source_conflicts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class OutlineSection(StrictModel):
    slide_id: str = Field(pattern=r"^slide-[0-9]{3,}$")
    title: str = Field(min_length=1)
    learning_objectives: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    estimated_minutes: float = Field(gt=0, le=120)


class ContentOutline(StrictModel):
    project_id: str
    title: str = Field(min_length=1)
    audience: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    sections: list[OutlineSection] = Field(min_length=1)
    total_minutes: float = Field(gt=0, le=600)

    @model_validator(mode="after")
    def _unique_slide_ids(self) -> ContentOutline:
        identifiers = [item.slide_id for item in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("slide_id values must be unique")
        return self


# --- Course planning contracts (P0-A) -------------------------------------
#
# These models describe *what a course must teach* before any unit text is
# generated. They live under ``internal/`` because PaperMap/CoverageMatrix and
# LearningUnit carry evidence and claim references that must never reach a
# public page.

PaperElementKind = Literal[
    "section",
    "equation",
    "figure",
    "table",
    "experiment",
    "result",
    "ablation",
    "complexity",
    "limitation",
    "conclusion",
]
PaperElementStatus = Literal[
    "verified",
    "unverified",
    "not_found",
    "not_applicable",
    "needs_review",
]
CoverageStatus = Literal["covered", "partial", "missing", "not_applicable"]


class PaperElement(StrictModel):
    """One thing the source paper contains or is expected to contain."""

    paper_item_id: str = Field(pattern=r"^paper-[0-9]{3,}$")
    kind: PaperElementKind
    title: str = Field(min_length=1)
    locator: str = ""
    required: bool = True
    status: PaperElementStatus = "unverified"
    evidence_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class PaperElementDraft(StrictModel):
    """One paper element found by the model inside a chunk window.

    The program assigns ``paper_item_id`` when merging, so IDs stay unique
    across calls and a model cannot overwrite an existing element.
    """

    kind: PaperElementKind
    title: str = Field(min_length=1)
    locator: str = ""
    notes: str = ""


class SectionAnalysis(StrictModel):
    """Model output for one sectioned-research window (not the whole paper)."""

    section: str = ""
    summary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    paper_elements: list[PaperElementDraft] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_conflicts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_local_ids(self) -> SectionAnalysis:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim_id values must be unique within a window")
        evidence_ids = [record.evidence_id for record in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique within a window")
        return self


class PaperMap(StrictModel):
    """Structural map of the source paper, built before the course outline."""

    project_id: str
    source_ids: list[str] = Field(default_factory=list)
    parser: str = ""
    generated_at: datetime = Field(default_factory=utc_now)
    elements: list[PaperElement] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_item_ids(self) -> PaperMap:
        identifiers = [item.paper_item_id for item in self.elements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("paper_item_id values must be unique")
        return self


class CoverageEntry(StrictModel):
    """Where one paper element is taught (or why it is not)."""

    paper_item_id: str = Field(pattern=r"^paper-[0-9]{3,}$")
    required: bool = True
    covered_by: list[str] = Field(default_factory=list)
    status: CoverageStatus = "missing"
    evidence_ids: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _status_matches_units(self) -> CoverageEntry:
        if self.status in {"covered", "partial"} and not self.covered_by:
            raise ValueError("covered/partial coverage requires at least one unit")
        if self.status in {"missing", "not_applicable"} and self.covered_by:
            raise ValueError("missing/not_applicable coverage must not name units")
        return self


class CoverageMatrix(StrictModel):
    project_id: str
    paper_map_sha256: str = Field(default="", pattern=r"^(|[0-9a-f]{64})$")
    entries: list[CoverageEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_paper_items(self) -> CoverageMatrix:
        identifiers = [item.paper_item_id for item in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("coverage entries must be unique per paper_item_id")
        return self


class ParagraphBlock(StrictModel):
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1)


class BulletsBlock(StrictModel):
    type: Literal["bullets"] = "bullets"
    items: list[str] = Field(min_length=1)


class FormulaBlock(StrictModel):
    type: Literal["formula"] = "formula"
    latex: str = Field(min_length=1)
    explanation: str = ""


class CodeBlock(StrictModel):
    type: Literal["code"] = "code"
    language: str = "text"
    code: str = Field(min_length=1)
    caption: str = ""


class FigureBlock(StrictModel):
    type: Literal["figure"] = "figure"
    path: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    caption: str = ""


class TableBlock(StrictModel):
    type: Literal["table"] = "table"
    caption: str = ""
    columns: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def _row_width(self) -> TableBlock:
        width = len(self.columns)
        for index, row in enumerate(self.rows, start=1):
            if len(row) != width:
                raise ValueError(f"table row {index} has {len(row)} cells, expected {width}")
        return self


class ChartBlock(StrictModel):
    """A statistical chart described by data plus a Vega-Lite spec.

    The rendered SVG is derived at build time; the block carries no markup.
    """

    type: Literal["chart"] = "chart"
    caption: str = ""
    alt: str = Field(min_length=1)
    spec: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty_spec(self) -> ChartBlock:
        if not self.spec:
            raise ValueError("chart spec must not be empty")
        return self


class DiagramBlock(StrictModel):
    """A flowchart or sequence diagram written in Mermaid source."""

    type: Literal["diagram"] = "diagram"
    mermaid: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    caption: str = ""


class GraphBlock(StrictModel):
    """A relationship graph written in Graphviz DOT."""

    type: Literal["graph"] = "graph"
    dot: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    caption: str = ""


class AnimationBlock(StrictModel):
    """An animation backed by a structured scene file, never generated code.

    P2.1 admits one animation per course and one scene per animation. The
    scene file lives under ``content/scenes/`` and is validated by the
    renderer's contract before any frames are produced.
    """

    type: Literal["animation"] = "animation"
    scene_file: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    caption: str = ""

    @field_validator("scene_file")
    @classmethod
    def _scene_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if normalized.startswith("/") or ".." in parts or ":" in parts[0]:
            raise ValueError("scene_file must be relative to the project workspace")
        if not normalized.startswith("content/scenes/"):
            raise ValueError("scene_file must live under content/scenes/")
        if not normalized.endswith(".json"):
            raise ValueError("scene_file must be a .json file")
        return normalized


class CalloutBlock(StrictModel):
    type: Literal["callout"] = "callout"
    kind: Literal["note", "warning", "limitation", "assumption"] = "note"
    text: str = Field(min_length=1)


class CheckBlock(StrictModel):
    """A learning check with an answer and the reasoning behind it."""

    type: Literal["check"] = "check"
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    rationale: str = ""


class QuoteBlock(StrictModel):
    type: Literal["quote"] = "quote"
    text: str = Field(min_length=1)
    attribution: str = ""


PublicBlock = Annotated[
    Union[
        ParagraphBlock,
        BulletsBlock,
        FormulaBlock,
        CodeBlock,
        FigureBlock,
        TableBlock,
        ChartBlock,
        DiagramBlock,
        GraphBlock,
        AnimationBlock,
        CalloutBlock,
        CheckBlock,
        QuoteBlock,
    ],
    Field(discriminator="type"),
]


UnitType = Literal["concept", "formula", "algorithm", "experiment", "comparison", "application"]
UnitStatus = Literal[
    "planned",
    "generating",
    "generated",
    "validating",
    "approved",
    "needs_revision",
    "blocked",
    "retryable_failure",
    "cancelled",
]
COURSE_MASTER_SCHEMA_VERSION = "1.0"
COURSE_MASTER_SCHEMA_MAJOR = "1"


class LearningUnit(StrictModel):
    """The unit of generation and review. One unit may span several slides.

    ``body`` is public content; ``narration`` and the evidence/claim refs are
    internal. The assembler splits this model into ``PublicContent`` and
    ``SpeakerScript``; a template must never receive it directly.
    """

    unit_id: str = Field(pattern=r"^unit-[0-9]{3,}$")
    chapter_id: str = Field(pattern=r"^chapter-[0-9]{3,}$")
    title: str = Field(min_length=1)
    unit_type: UnitType
    objectives: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    body: list[PublicBlock] = Field(default_factory=list)
    narration: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    paper_item_ids: list[str] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    estimated_minutes: float = Field(gt=0, le=120)
    status: UnitStatus = "planned"
    revision: int = Field(default=0, ge=0)
    generated_at: datetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _content_matches_status(self) -> LearningUnit:
        if self.status in {"generated", "validating", "approved"} and not self.body:
            raise ValueError(f"unit {self.unit_id} is {self.status} but has no body")
        return self


class CourseChapter(StrictModel):
    chapter_id: str = Field(pattern=r"^chapter-[0-9]{3,}$")
    title: str = Field(min_length=1)
    objectives: list[str] = Field(default_factory=list)
    unit_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


class CourseMaster(StrictModel):
    """Single internal source for the course; deliverable forms derive from it."""

    schema_version: str = COURSE_MASTER_SCHEMA_VERSION
    project_id: str
    title: str = Field(min_length=1)
    language: str = "zh-CN"
    audience: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    chapters: list[CourseChapter] = Field(min_length=1)
    units: list[LearningUnit] = Field(min_length=1)
    coverage: list[CoverageEntry] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    status: Literal["draft", "in_review", "approved"] = "draft"

    @field_validator("schema_version")
    @classmethod
    def _supported_major(cls, value: str) -> str:
        if value.split(".", 1)[0] != COURSE_MASTER_SCHEMA_MAJOR:
            raise ValueError(
                f"unsupported course master schema_version '{value}'; "
                f"this build supports {COURSE_MASTER_SCHEMA_MAJOR}.x"
            )
        return value

    @model_validator(mode="after")
    def _consistent_structure(self) -> CourseMaster:
        chapter_ids = [chapter.chapter_id for chapter in self.chapters]
        if len(chapter_ids) != len(set(chapter_ids)):
            raise ValueError("chapter_id values must be unique")
        unit_ids = [unit.unit_id for unit in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("unit_id values must be unique")
        by_id = {unit.unit_id: unit for unit in self.units}
        ordered: list[str] = []
        for chapter in self.chapters:
            for unit_id in chapter.unit_ids:
                unit = by_id.get(unit_id)
                if unit is None:
                    raise ValueError(
                        f"chapter {chapter.chapter_id} references unknown unit {unit_id}"
                    )
                if unit.chapter_id != chapter.chapter_id:
                    raise ValueError(
                        f"unit {unit_id} belongs to {unit.chapter_id}, not {chapter.chapter_id}"
                    )
                ordered.append(unit_id)
        if ordered != unit_ids:
            raise ValueError("units must be listed once, in chapter order")
        known = set(unit_ids)
        for entry in self.coverage:
            unknown = [unit_id for unit_id in entry.covered_by if unit_id not in known]
            if unknown:
                raise ValueError(
                    f"coverage for {entry.paper_item_id} names unknown units: {unknown}"
                )
        return self


# Visual specs are a separate contract from the content blocks that reference
# them: content says *what* to show, the spec says *how* it is rendered.
VISUAL_SCHEMA_VERSION = "1.0"
VISUAL_SCHEMA_MAJOR = "1"


class VisualValidation(StrictModel):
    """Renderer-reported state. A model can never set ``approved`` here."""

    required: bool = True
    status: Literal["pending", "valid", "invalid"] = "pending"
    message: str = ""


class VisualSpec(StrictModel):
    schema_version: str = VISUAL_SCHEMA_VERSION
    visual_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    visual_type: str = Field(min_length=1)
    title: str = ""
    # Empty means "use the registry default for this visual_type"; a non-empty
    # value must match the resolved renderer or rendering fails.
    renderer: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    validation: VisualValidation = Field(default_factory=VisualValidation)

    @field_validator("schema_version")
    @classmethod
    def _supported_major(cls, value: str) -> str:
        major = value.split(".", 1)[0]
        if major != VISUAL_SCHEMA_MAJOR:
            raise ValueError(
                f"unsupported visual schema_version '{value}'; "
                f"this build supports {VISUAL_SCHEMA_MAJOR}.x"
            )
        return value


# --- Visual asset, scene, and video contracts (PRD 2 module 1) -------------

AssetType = Literal[
    "diagram", "svg", "chart", "table", "animation", "scene", "video", "audio", "image"
]
AssetStatus = Literal["pending", "rendered", "failed", "skipped"]
TransitionKind = Literal["cut", "fade", "slide", "zoom", "none"]
FallbackPolicy = Literal["fail", "skip", "placeholder"]
_HASH = r"^[0-9a-f]{64}$"


def _relative_path(value: str) -> str:
    """Reject absolute paths, drive letters, and parent traversal."""

    if not value.strip():
        raise ValueError("path must not be empty")
    if re.match(r"^[A-Za-z]:", value) or value.startswith("\\\\"):
        raise ValueError(f"path must be relative to the project workspace: {value}")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must stay inside the project workspace: {value}")
    return value


class AssetCheck(StrictModel):
    check_id: str = Field(min_length=1)
    status: Literal["pass", "fail", "warn", "not_run"]
    message: str = ""


class VisualAsset(StrictModel):
    """One rendered (or to-be-rendered) visual artifact and its provenance."""

    schema_version: str = VISUAL_SCHEMA_VERSION
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    asset_type: AssetType
    source: str
    renderer: str = ""
    renderer_version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    output_paths: list[str] = Field(default_factory=list)
    status: AssetStatus = "pending"
    qa_results: list[AssetCheck] = Field(default_factory=list)
    source_hash: str = Field(default="", pattern=r"^$|" + _HASH)
    output_hashes: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    build_id: str = ""

    @field_validator("schema_version")
    @classmethod
    def _asset_schema_major(cls, value: str) -> str:
        if value.split(".", 1)[0] != VISUAL_SCHEMA_MAJOR:
            raise ValueError(f"unsupported asset schema_version '{value}'")
        return value

    @field_validator("source", "dependencies", "output_paths")
    @classmethod
    def _asset_paths(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return _relative_path(value)
        return [_relative_path(item) for item in value]

    @field_validator("output_hashes")
    @classmethod
    def _output_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        for path, digest in value.items():
            if not re.fullmatch(_HASH, digest):
                raise ValueError(f"output hash for {path} is not a sha256 digest")
        return value


class SceneContract(StrictModel):
    """One shot in a video timeline. Durations are integer milliseconds."""

    schema_version: str = VISUAL_SCHEMA_VERSION
    scene_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    scene_type: str = Field(min_length=1)
    duration_ms: int = Field(gt=0)
    renderer: str = ""
    source_asset_refs: list[str] = Field(default_factory=list)
    narration_ref: str = ""
    subtitle_ref: str = ""
    transition_in: TransitionKind = "cut"
    transition_out: TransitionKind = "cut"
    camera_config: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    quality_profile: str = "default"
    fallback_policy: FallbackPolicy = "fail"
    # Template payload (title text, accent colour, ...). Kept as data so the
    # contract does not hard-code one template's fields; the renderer's
    # validate_input() is what admits or rejects a template shape.
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _scene_schema_major(cls, value: str) -> str:
        if value.split(".", 1)[0] != VISUAL_SCHEMA_MAJOR:
            raise ValueError(f"unsupported scene schema_version '{value}'")
        return value


class SceneSet(StrictModel):
    """Ordered scenes for one video build.

    The list order *is* the timeline order. Canvas, frame rate, and encoding
    stay in :class:`VideoContract`; this model must not restate them.
    """

    schema_version: str = VISUAL_SCHEMA_VERSION
    scenes: list[SceneContract] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _scene_set_schema_major(cls, value: str) -> str:
        if value.split(".", 1)[0] != VISUAL_SCHEMA_MAJOR:
            raise ValueError(f"unsupported scene set schema_version '{value}'")
        return value

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> SceneSet:
        seen: set[str] = set()
        for scene in self.scenes:
            if scene.scene_id in seen:
                raise ValueError(f"duplicate scene_id '{scene.scene_id}' in scene set")
            seen.add(scene.scene_id)
        return self

    @property
    def scene_ids(self) -> list[str]:
        return [scene.scene_id for scene in self.scenes]


class VideoContract(StrictModel):
    """A video build: canvas, timing, tracks, encoding, and provenance."""

    schema_version: str = VISUAL_SCHEMA_VERSION
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    video_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    content_version: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    # Rational frame rate: 30000/1001 is 29.97 fps, with no float drift.
    fps_num: int = Field(gt=0)
    fps_den: int = Field(default=1, gt=0)
    color_space: str = "bt709"
    pixel_format: str = "yuv420p"
    scene_ids: list[str] = Field(min_length=1)
    narration_ref: str = ""
    audio_refs: list[str] = Field(default_factory=list)
    subtitle_language: str = "zh-CN"
    subtitle_format: Literal["srt", "vtt"] = "srt"
    audio_sample_rate: int = Field(default=48_000, gt=0)
    audio_channels: Literal[1, 2] = 2
    video_codec: str = "h264"
    quality_preset: str = "medium"
    renderer: str = ""
    renderer_version: str = ""
    output_path: str
    qa_report_ref: str = ""
    provenance: str = ""
    licence: str = ""
    build_parameters: dict[str, Any] = Field(default_factory=dict)
    build_hash: str = Field(default="", pattern=r"^$|" + _HASH)

    @field_validator("schema_version")
    @classmethod
    def _video_schema_major(cls, value: str) -> str:
        if value.split(".", 1)[0] != VISUAL_SCHEMA_MAJOR:
            raise ValueError(f"unsupported video schema_version '{value}'")
        return value

    @field_validator("output_path")
    @classmethod
    def _video_output(cls, value: str) -> str:
        return _relative_path(value)

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den


class FrameEntry(StrictModel):
    """One exported frame, with the evidence needed to re-check it."""

    index: int = Field(ge=0)
    path: str
    sha256: str = Field(pattern=_HASH)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    decodable: bool = True

    @field_validator("path")
    @classmethod
    def _frame_path(cls, value: str) -> str:
        return _relative_path(value)


class SceneFrameSpan(StrictModel):
    """Half-open frame range owned by one scene."""

    scene_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> SceneFrameSpan:
        if self.end_frame <= self.start_frame:
            raise ValueError(f"scene '{self.scene_id}': end_frame must be greater than start_frame")
        return self


class FrameManifest(StrictModel):
    """Versioned evidence for a rendered frame sequence.

    The manifest never replaces verification: every path is re-hashed and
    re-decoded by ``frame_manifest.verify_frame_manifest``.
    """

    schema_version: str = VISUAL_SCHEMA_VERSION
    build_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    fps_num: int = Field(gt=0)
    fps_den: int = Field(default=1, gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    format: Literal["png"] = "png"
    total_frames: int = Field(gt=0)
    scenes: list[SceneFrameSpan] = Field(min_length=1)
    frames: list[FrameEntry] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _manifest_schema_major(cls, value: str) -> str:
        if value.split(".", 1)[0] != VISUAL_SCHEMA_MAJOR:
            raise ValueError(f"unsupported frame manifest schema_version '{value}'")
        return value

    @model_validator(mode="after")
    def _complete(self) -> FrameManifest:
        if len(self.frames) != self.total_frames:
            raise ValueError(
                f"manifest lists {len(self.frames)} frames but declares {self.total_frames}"
            )
        indices = [frame.index for frame in self.frames]
        if indices != list(range(self.total_frames)):
            raise ValueError("frame indices must be contiguous from 0")
        start = 0
        for span in self.scenes:
            if span.start_frame != start:
                raise ValueError(
                    f"scene '{span.scene_id}' starts at {span.start_frame}, expected {start}"
                )
            start = span.end_frame
        if start != self.total_frames:
            raise ValueError(f"scene spans cover {start} frames, expected {self.total_frames}")
        return self


class PublicSlide(StrictModel):
    slide_id: str = Field(pattern=r"^slide-[0-9]{3,}$")
    title: str = Field(min_length=1)
    body: list[PublicBlock] = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


class PublicContent(StrictModel):
    """Public-only model. Never add speaker notes or internal QA fields here."""

    project_id: str
    title: str = Field(min_length=1)
    subtitle: str = ""
    language: str = "zh-CN"
    audience: str = ""
    slides: list[PublicSlide] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_slide_ids(self) -> PublicContent:
        identifiers = [item.slide_id for item in self.slides]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("slide_id values must be unique")
        return self


class ScriptSection(StrictModel):
    slide_id: str = Field(pattern=r"^slide-[0-9]{3,}$")
    narration: str = Field(min_length=1)
    pronunciation_notes: list[str] = Field(default_factory=list)
    estimated_seconds: int = Field(default=0, ge=0, le=3600)


class SpeakerScript(StrictModel):
    """Internal model. Must never be rendered into public HTML."""

    project_id: str
    language: str = "zh-CN"
    sections: list[ScriptSection] = Field(min_length=1)
    total_estimated_seconds: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_slide_ids(self) -> SpeakerScript:
        identifiers = [item.slide_id for item in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("slide_id values must be unique")
        return self


class ReadingSection(StrictModel):
    slide_id: str = Field(pattern=r"^slide-[0-9]{3,}$")
    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


class ReadingEdition(StrictModel):
    project_id: str
    title: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    sections: list[ReadingSection] = Field(min_length=1)
    references: list[str] = Field(default_factory=list)


class CheckResult(StrictModel):
    check_id: str
    gate: GateId
    status: CheckStatus
    message: str
    blocking: bool = True


class QAReport(StrictModel):
    project_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    provider: str = ""
    model: str = ""
    checks: list[CheckResult] = Field(default_factory=list)

    @property
    def blocking_failures(self) -> list[CheckResult]:
        return [item for item in self.checks if item.status == "fail" and item.blocking]

    @property
    def not_run(self) -> list[CheckResult]:
        return [item for item in self.checks if item.status == "not_run"]

    @property
    def passed(self) -> bool:
        return not self.blocking_failures

    def gate_status(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for gate in ("gate_1_research", "gate_2_content", "gate_3_engineering", "gate_4_release"):
            results = [item for item in self.checks if item.gate == gate]
            if not results:
                continue
            if any(item.status == "fail" and item.blocking for item in results):
                statuses[gate] = "fail"
            elif any(item.status == "fail" for item in results):
                statuses[gate] = "warn"
            elif any(item.status == "warn" for item in results):
                statuses[gate] = "warn"
            elif any(item.status == "not_run" for item in results):
                statuses[gate] = "partial"
            else:
                statuses[gate] = "pass"
        return statuses


class ApprovalRecord(StrictModel):
    project_id: str
    version: str
    approved_by: str = Field(min_length=1)
    approved_at: datetime = Field(default_factory=utc_now)
    scope: str = "release"
    notes: str = ""


class ManifestFile(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = "application/octet-stream"


class ReleaseManifest(StrictModel):
    project_id: str
    version: str
    generated_at: datetime = Field(default_factory=utc_now)
    package_version: str
    python_version: str
    provider: str = ""
    model: str = ""
    content_sha256: str = ""
    gates: dict[str, str] = Field(default_factory=dict)
    human_approval: ApprovalRecord | None = None
    files: list[ManifestFile] = Field(default_factory=list)
