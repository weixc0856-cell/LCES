"""Unified data contracts.

These models are the single source of truth for JSON Schemas (see
``lces export-schemas``). The public content model is deliberately separate
from the internal speaker script: no template may read narration fields, and
``extra="forbid"`` keeps internal fields from leaking into public data.
"""

from __future__ import annotations

from datetime import datetime
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
    "quote", "data", "figure", "table", "experiment", "official_statement", "analysis"
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


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(pattern=r"^evidence-[0-9]{3,}$")
    source_id: str
    claim_id: str
    evidence_type: EvidenceType
    locator: str = ""
    source_excerpt: str = Field(default="", max_length=2000)
    support_relation: SupportRelation
    verification_status: VerificationStatus = "unverified"
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


class CalloutBlock(StrictModel):
    type: Literal["callout"] = "callout"
    kind: Literal["note", "warning", "limitation", "assumption"] = "note"
    text: str = Field(min_length=1)


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
        CalloutBlock,
        QuoteBlock,
    ],
    Field(discriminator="type"),
]


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
