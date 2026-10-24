"""Build read-only evidence review packets for a human reviewer.

Each packet answers one question: what exactly is being claimed, where does it
come from, where does the course use it, what is still ambiguous, and what
must the reviewer decide? The builder never writes to the review record, never
signs, and marks a source ``unresolved`` instead of inventing a locator.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from content_studio.content import load_public_content, load_reading_edition, load_speaker_script
from content_studio.ingestion import load_registry
from content_studio.models import StrictModel
from content_studio.planning import load_paper_map
from content_studio.source_map import load_source_map
from content_studio.structured_review import ReviewItem, default_review_path, load_review
from content_studio.utils import utc_now, write_json_atomic

PACKET_VERSION = "1.0"
_DECIMAL = re.compile(r"\d+\.\d+")
_FORMULA_KEYWORDS = {
    "review-formula-attention": ("Attention",),
    "review-formula-multihead": ("MultiHead",),
    "review-formula-positional": ("PE_", "sin(", "cos("),
}


class CourseUsage(StrictModel):
    path: str
    location: str
    text: str


class SourceEvidence(StrictModel):
    source_id: str
    title: str
    origin: str
    version: str = ""
    locator: str
    chunk_id: str
    chunk_section: str = ""
    char_start: int = 0
    char_end: int = 0
    excerpt: str = ""
    excerpt_sha256: str = ""
    source_text_sha256: str = ""
    unresolved: bool = False
    note: str = ""


class ReviewPacket(StrictModel):
    packet_version: str = PACKET_VERSION
    packet_sha256: str = ""
    review_id: str
    generated_at: datetime
    claim: str
    evidence_kind: Literal["table", "formula"]
    paper_id: str
    paper_title: str = ""
    paper_locator: str = ""
    source_id: str
    chunk_id: str
    locator: str
    program_status: str
    program_reason: str
    research_finding: str
    external_source_url: str = ""
    external_source_version: str = ""
    external_source_locator: str = ""
    source: SourceEvidence
    course_usage: list[CourseUsage] = Field(default_factory=list)
    support_scope: str = ""
    counter_evidence: str = ""
    limitations: str = ""
    ambiguities: list[str] = Field(default_factory=list)
    reviewer_questions: list[str] = Field(default_factory=list)
    conclusion_options: list[str] = Field(
        default_factory=lambda: ["pass", "needs_revision", "blocked", "fail"]
    )
    current_conclusion: str = "pending"
    signature: dict[str, str] = Field(default_factory=dict)
    cli_command: str = ""


class PacketEntry(StrictModel):
    review_id: str
    claim: str
    packet_path: str
    packet_sha256: str
    current_conclusion: str


class PacketIndex(StrictModel):
    packet_version: str = PACKET_VERSION
    project_id: str
    generated_at: datetime
    review_file_sha256: str
    source_text_sha256: str
    packets: list[PacketEntry] = Field(default_factory=list)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _packet_hash(packet: ReviewPacket) -> str:
    payload = packet.model_dump(mode="json", exclude={"packet_sha256", "generated_at"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _course_units(project_dir: Path) -> list[CourseUsage]:
    units: list[CourseUsage] = []
    public = load_public_content(project_dir)
    if public is not None:
        for slide in public.slides:
            for index, block in enumerate(slide.body):
                location = f"content/public_content.json#{slide.slide_id}:{block.type}[{index}]"
                for text in _block_texts(block):
                    if text.strip():
                        units.append(
                            CourseUsage(
                                path="content/public_content.json", location=location, text=text
                            )
                        )
    reading = load_reading_edition(project_dir)
    if reading is not None:
        for section in reading.sections:
            for index, paragraph in enumerate(section.paragraphs):
                units.append(
                    CourseUsage(
                        path="content/reading_edition.json",
                        location=f"content/reading_edition.json#{section.slide_id}:paragraph[{index}]",
                        text=paragraph,
                    )
                )
    script = load_speaker_script(project_dir)
    if script is not None:
        for script_section in script.sections:
            units.append(
                CourseUsage(
                    path="internal/speaker_script.json",
                    location=(f"internal/speaker_script.json#{script_section.slide_id}:narration"),
                    text=script_section.narration,
                )
            )
    return units


def _block_texts(block: object) -> list[str]:
    texts: list[str] = []
    for attribute in ("text", "explanation", "caption", "question", "answer", "rationale", "latex"):
        value = getattr(block, attribute, "")
        if isinstance(value, str) and value:
            texts.append(value)
    items = getattr(block, "items", None)
    if isinstance(items, list):
        texts.extend(str(item) for item in items)
    rows = getattr(block, "rows", None)
    if isinstance(rows, list):
        texts.extend(" | ".join(str(cell) for cell in row) for row in rows)
    return texts


def _needles(item: ReviewItem) -> list[str]:
    """Search keys for the course: numbers for tables, formula names for formulas.

    Generic words such as ``base`` or ``softmax`` match unrelated sections, so
    they are deliberately not used to find course usage.
    """

    if item.review_id in _FORMULA_KEYWORDS:
        return list(_FORMULA_KEYWORDS[item.review_id])
    return sorted(set(_DECIMAL.findall(item.claim)))


def _course_usage(
    units: list[CourseUsage], needles: list[str], limit: int = 6
) -> list[CourseUsage]:
    matched: list[CourseUsage] = []
    lowered = [(needle.lower(), needle) for needle in needles]
    for unit in units:
        text_lower = unit.text.lower()
        if any(needle_lower in text_lower for needle_lower, _needle in lowered):
            matched.append(unit)
        if len(matched) >= limit:
            break
    return matched


def _source_evidence(project_dir: Path, item: ReviewItem) -> SourceEvidence:
    registry = load_registry(project_dir)
    record = None
    if registry is not None:
        record = next(
            (source for source in registry.sources if source.source_id == item.source_id), None
        )
    source_map = load_source_map(project_dir)
    chunk = None
    if source_map is not None:
        for document in source_map.documents:
            for candidate in document.chunks:
                if candidate.chunk_id == item.chunk_id:
                    chunk = candidate
                    break
    source_path = project_dir / "internal" / "sources" / f"{item.source_id}.txt"
    source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
    title = record.title if record is not None else item.source_id
    origin = record.origin if record is not None else ""
    version = ""
    if "1706.03762v7" in origin:
        version = "arXiv HTML v7"
    elif origin:
        version = origin
    if chunk is None or not source_text:
        return SourceEvidence(
            source_id=item.source_id,
            title=title,
            origin=origin,
            locator=item.locator,
            version=version,
            chunk_id=item.chunk_id,
            source_text_sha256=_sha256_text(source_text),
            unresolved=True,
            note="source text or chunk not found; reviewer must locate the source manually",
        )

    chunk_text = source_text[chunk.char_start : chunk.char_end]
    needles = _needles(item)
    excerpt = chunk_text[:800]
    matched = next(
        (needle for needle in needles if needle and needle.lower() in chunk_text.lower()), ""
    )
    if matched:
        position = chunk_text.lower().find(matched.lower())
        start = max(0, position - 240)
        end = min(len(chunk_text), position + 420)
        excerpt = chunk_text[start:end]
    return SourceEvidence(
        source_id=item.source_id,
        title=title,
        origin=origin,
        locator=item.locator,
        version=version,
        chunk_id=item.chunk_id,
        chunk_section=chunk.section,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        excerpt=excerpt,
        excerpt_sha256=_sha256_text(excerpt),
        source_text_sha256=_sha256_text(source_text),
        unresolved=False,
        note="excerpt sliced from the stored source around the reviewed locator"
        if matched
        else "no keyword matched inside the chunk; the first 800 characters are shown",
    )


def _questions(item: ReviewItem) -> list[str]:
    common = [
        "该主张的限定语（模型规模、语言方向、数据集、指标）是否完整且与原文一致？",
        "记录的来源、区块与 locator 是否能在原文中独立复核？",
    ]
    if item.evidence_kind == "formula":
        return [
            "公式的转录、符号、上下标、运算符和维度是否与原文逐项一致？",
            "课程对该公式的解释是否超出原文支持范围？",
            *common,
        ]
    if item.conflict_status != "none":
        return [
            "两版来源（NeurIPS 与 arXiv）的表格与正文分别写了什么？",
            "课程采用的口径是否明确、在正文/阅读版/口播中是否一致披露？",
            "冲突是否被如实保留，而不是被静默择一或取平均？",
            *common,
        ]
    return [
        "该数值是否确实属于该行、该列、该模型规模、该语言方向和该数据集？",
        "表格脚注或正文是否改变了这个数值的适用范围？",
        *common,
    ]


def build_packet(project_dir: Path, item: ReviewItem) -> ReviewPacket:
    research = item.research_verification[0] if item.research_verification else None
    limitations = research.limitations if research is not None else ""
    support_scope = "；".join(
        part
        for part in (
            f"research_finding={research.research_finding}" if research else "",
            f"program={item.program_status}/{item.program_reason}",
        )
        if part
    )
    counter = ""
    if item.conflict_status != "none":
        counter = "同一来源内部或不同版本之间存在 41.0 / 41.8 的不一致；不得自动裁决。"
    ambiguities = [
        value for value in (item.missing.strip(), item.program_precheck.strip()) if value
    ]
    source = _source_evidence(project_dir, item)
    paper_title = ""
    paper_locator = ""
    paper_map = load_paper_map(project_dir)
    if paper_map is not None:
        element = next(
            (entry for entry in paper_map.elements if entry.paper_item_id == item.paper_id),
            None,
        )
        if element is not None:
            paper_title = element.title
            paper_locator = element.locator
    packet = ReviewPacket(
        review_id=item.review_id,
        generated_at=utc_now(),
        claim=item.claim,
        evidence_kind=item.evidence_kind,
        paper_id=item.paper_id,
        paper_title=paper_title,
        paper_locator=paper_locator,
        source_id=item.source_id,
        chunk_id=item.chunk_id,
        locator=item.locator,
        program_status=item.program_status,
        program_reason=item.program_reason,
        research_finding=research.research_finding if research is not None else "",
        external_source_url=research.source_url if research is not None else "",
        external_source_version=research.source_version if research is not None else "",
        external_source_locator=research.source_locator if research is not None else "",
        source=source,
        course_usage=_course_usage(_course_units(project_dir), _needles(item)),
        support_scope=support_scope,
        counter_evidence=counter,
        limitations=limitations,
        ambiguities=ambiguities,
        reviewer_questions=_questions(item),
        current_conclusion=item.conclusion,
        signature={
            "reviewer": "",
            "reviewed_at": "",
            "conclusion": "pending",
            "basis": "",
            "conflict_acknowledged": "false",
        },
        cli_command=(
            f"uv run lces review-evidence .\\projects\\{project_dir.name} "
            f'--review-id {item.review_id} --by "<审核者>" --conclusion pass '
            '--basis "<核对原文后的依据>"'
            + (" --conflict-ack" if item.conflict_status != "none" else "")
        ),
    )
    return packet.model_copy(update={"packet_sha256": _packet_hash(packet)})


def build_packets(project_dir: Path, output_dir: Path) -> tuple[list[PacketEntry], PacketIndex]:
    project_dir = project_dir.resolve()
    review_path = default_review_path(project_dir)
    document = load_review(review_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries: list[PacketEntry] = []
    for item in document.items:
        packet = build_packet(project_dir, item)
        path = output_dir / f"{item.review_id}.json"
        write_json_atomic(path, packet)
        entries.append(
            PacketEntry(
                review_id=item.review_id,
                claim=item.claim,
                packet_path=path.name,
                packet_sha256=packet.packet_sha256,
                current_conclusion=item.conclusion,
            )
        )
    source_path = project_dir / "internal" / "sources" / "source-001.txt"
    index = PacketIndex(
        project_id=document.project_id,
        generated_at=utc_now(),
        review_file_sha256=_sha256_file(review_path),
        source_text_sha256=_sha256_file(source_path) if source_path.is_file() else "",
        packets=entries,
    )
    write_json_atomic(output_dir / "index.json", index)
    lines = [
        "# 证据审核包索引",
        "",
        f"- project: `{document.project_id}`",
        f"- review file sha256: `{index.review_file_sha256}`",
        f"- source-001 sha256: `{index.source_text_sha256}`",
        "",
        "| review_id | 主张 | 结论 | 审核包 |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| `{entry.review_id}` | {entry.claim[:70]} | `{entry.current_conclusion}` | "
        f"[{entry.packet_path}]({entry.packet_path}) |"
        for entry in entries
    ]
    (output_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entries, index


__all__ = [
    "CourseUsage",
    "PacketIndex",
    "ReviewPacket",
    "SourceEvidence",
    "build_packet",
    "build_packets",
]
