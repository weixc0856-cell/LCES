"""Research and evidence governance (Skill: knowledge-learning-studio)."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from content_studio.errors import ValidationFailure
from content_studio.evidence_locator import (
    QuoteAudit,
    QuoteCandidate,
    merge_audits,
    validate_candidates,
)
from content_studio.ingestion import load_registry, load_source_text
from content_studio.models import (
    Claim,
    EvidenceLedger,
    EvidenceRecord,
    PaperElement,
    PaperElementDraft,
    PaperMap,
    ProjectConfig,
    ResearchAnalysis,
    ResearchBrief,
    ResearchFinding,
    SectionAnalysis,
    SourceChunk,
    SourceDocumentMap,
    SourceRecord,
)
from content_studio.planning import load_paper_map
from content_studio.providers.base import (
    DEFAULT_MAX_TOKENS,
    GenerationRequest,
    Message,
    ModelProvider,
)
from content_studio.source_map import chunk_text, ensure_source_map
from content_studio.structured_evidence import (
    StructuredAudit,
    merge_structured_audits,
    review_for,
    validate_structured_record,
)
from content_studio.utils import utc_now, write_json, write_text

EVIDENCE_COLUMNS = [
    "evidence_id",
    "source_id",
    "chunk_id",
    "claim_id",
    "evidence_type",
    "locator",
    "source_excerpt",
    "support_relation",
    "verification_status",
    "quote_status",
    "structured_json",
    "reviewer",
    "checked_at",
    "notes",
]

SECTION_PROMPT = """你是 LCES 的分节研究模块（knowledge-learning-studio）。
规则：
1. 只使用本窗口给出的原始文本；不得引用窗口外内容，也不得凭记忆补充。
2. 每条 evidence 必须指向窗口中的 source_id；locator 使用区块头给出的章节或页码；
   source_excerpt 必须逐字摘自原文（不超过 200 字），不得包含系统添加的区块头。
3. claim/evidence 的 ID 在本窗口内唯一（从 claim-001、evidence-001 开始）；
   跨窗口的合并、去重与重新编号由程序完成。每条 evidence 必须填写区块头中的
   chunk_id，或至少填写 locator 的章节（如 §3.2.1）；source_excerpt 只能来自
   该章节内单一区块的连续原文，不能跨区块拼接。
4. 区分事实、推断、假设、未知与争议；不得把推断写成原文事实。
5. paper_elements 只登记窗口中真实出现的章节、公式、图、表、实验、结果、消融、
   复杂度、局限与结论；找不到就留空，不得补造。locator 写章节或页码。
6. 无法逐字摘录时把 source_excerpt 留空，并在 notes 说明原因。
7. verification_status 一律填 unverified；模型不能核验自己的输出。
8. 公式、表格、实验设置与数值结果是本轮的重点。即使原文含零宽字符、LaTeX
   残片或不规则排版，也要说明其含义；摘录必须是原文中连续可见的片段，不得
   把改写、补全或表格重排当成摘录。
9. 数值结果必须写明模型变体（base / big 等）、数据集、指标与比较对象。
   不得把某个变体的结果说成整个模型的结果。
10. 不提取参考文献、致谢、作者单位或页面导航；它们不是教学内容。
11. 每个窗口最多输出 10 条 claim、10 条 evidence、10 个 paper_elements。
    超出时优先保留公式、实验设置、关键结果、消融与局限，而不是背景描述。
12. 每个窗口的 key claim 不超过 3 条；只有直接支撑论文核心论证的才标 key，
    其余标 supporting。
13. 结果数值必须带变体限定：Transformer (base) 为 27.3 / 38.1，
    Transformer (big) 为 28.4 / 41.8；不得把 big 的结果写成整个模型。
14. 摘录不得使用省略号、表格拼接或补写；如果原文是表格，摘录表题或紧邻的
    结论句。不得把段落中的不同应用改写成新的并列类别（例如正则化类型）。
15. 公式证据使用 evidence_type=formula，并填写 formula 对象（formula_id、
    expression、symbols、locator）。公式不做自动语义通过，程序只检查结构，
    结论进入人工复核。
16. 表格证据使用 evidence_type=table，并填写 table 对象（table_id、scope、
    row_label、column_label、value、unit、variant、locator）。scope 为 cell/row
    表示表格单元格或行；表格旁的叙述句用 quote，不要用 table 冒充单元格。
    数值必须来自原文表格行；程序只把它作为结构检查，列语义仍需人工确认。
17. formula_id / table_id 优先使用下方论文要素中的 paper_item_id。
只输出符合给定 JSON Schema 的 JSON。"""

_REQUIRED_ELEMENT_KINDS = frozenset(
    {
        "equation",
        "table",
        "experiment",
        "result",
        "ablation",
        "complexity",
        "limitation",
        "conclusion",
    }
)
# Bibliography sections are not teaching content. They are recorded as
# intentionally excluded instead of being sent to the model.
_EXCLUDED_SECTION = re.compile(
    r"\b(references?|bibliography|acknowledg(?:e)?ments?)\b", re.IGNORECASE
)


@dataclass
class ChunkWindow:
    source_id: str
    chunks: list[SourceChunk]
    text: str

    @property
    def chunk_ids(self) -> list[str]:
        return [chunk.chunk_id for chunk in self.chunks]

    @property
    def section(self) -> str:
        labels: list[str] = []
        for chunk in self.chunks:
            if chunk.section and chunk.section not in labels:
                labels.append(chunk.section)
        return "; ".join(labels)

    @property
    def pages(self) -> str:
        pages = sorted({chunk.page for chunk in self.chunks if chunk.page is not None})
        if not pages:
            return "（无页码）"
        if len(pages) == 1:
            return f"p.{pages[0]}"
        return f"p.{pages[0]}–{pages[-1]}"

    @property
    def locator(self) -> str:
        return self.section or self.pages


def _page_label(page: int | None) -> str:
    return f"p.{page}" if page is not None else "（无页码）"


def _pack_windows(
    project_dir: Path,
    document: SourceDocumentMap,
    budget: int,
    chunks: list[SourceChunk],
    *,
    max_sections: int = 2,
    min_chars: int | None = None,
) -> list[ChunkWindow]:
    """Group chunks into complete windows; a chunk is never split or truncated.

    A window opens a new section segment when the section label changes. Once
    ``max_sections`` segments and ``min_chars`` of material are present, the
    next change flushes the window. Counting *changes* rather than unique
    labels keeps a table of contents from poisoning the count for the body.
    """

    text = load_source_text(project_dir, document.source_id)
    if not text or not chunks:
        return []
    if min_chars is None:
        min_chars = max(3000, budget // 3)
    windows: list[ChunkWindow] = []
    current: list[SourceChunk] = []
    current_text: list[str] = []
    current_changes = 0
    previous_section = ""
    current_size = 0
    for chunk in chunks:
        body = chunk_text(text, chunk)
        header = (
            f"### {chunk.chunk_id} | {chunk.section or '(未识别章节)'} | "
            f"{_page_label(chunk.page)}" + chr(10)
        )
        piece = header + body
        section = chunk.section or ""
        section_changed = bool(section and section != previous_section)
        too_many_sections = (
            section_changed
            and current_changes >= max_sections
            and current_size >= min_chars
            and bool(current)
        )
        if current and (current_size + len(piece) > budget or too_many_sections):
            windows.append(ChunkWindow(document.source_id, current, chr(10).join(current_text)))
            current, current_text, current_size = [], [], 0
            current_changes = 0
            previous_section = ""
            section_changed = bool(section)
        if section_changed:
            current_changes += 1
            previous_section = section
        current.append(chunk)
        current_text.append(piece)
        current_size += len(piece) + 1
    if current:
        windows.append(ChunkWindow(document.source_id, current, chr(10).join(current_text)))
    return windows


def _window_prompt(
    config: ProjectConfig,
    record: SourceRecord,
    window: ChunkWindow,
    paper_map: PaperMap | None = None,
) -> str:
    paper_lines: list[str] = []
    if paper_map is not None:
        for element in paper_map.elements:
            if element.kind in {"equation", "table"}:
                paper_lines.append(
                    f"{element.paper_item_id} | {element.kind} | "
                    f"{element.title} | {element.locator}"
                )
    paper_block = (
        "论文要素（公式/表格证据请优先引用 paper_item_id）：\n"
        + ("\n".join(paper_lines[:30]) or "（无）")
        + "\n\n"
    )
    return (
        f"项目: {config.title}（{config.project_id}）\n"
        f"任务类型: {config.content_mode}\n"
        f"受众: {config.audience}\n"
        f"语言: {config.language}\n\n"
        f"来源: {record.source_id} | {record.title}\n"
        f"获取状态: {record.access_status}\n"
        f"本窗口章节: {window.section or '（未识别）'}\n"
        f"本窗口页码: {window.pages}\n"
        f"本窗口区块: {window.chunk_ids[0]}–{window.chunk_ids[-1]}"
        f"（{len(window.chunk_ids)} 个）\n\n"
        + paper_block
        + "以下为原文区块。区块头由系统添加，不属于原文；摘录时不得包含区块头。\n\n"
        + window.text
    )


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _reset_claim(claim: Claim) -> Claim:
    return claim.model_copy(
        update={"verification_status": "pending", "reviewer": "", "reviewed_at": None}
    )


def _reset_evidence(record: EvidenceRecord) -> EvidenceRecord:
    return record.model_copy(
        update={"verification_status": "unverified", "reviewer": "", "checked_at": None}
    )


def _merge_claims(
    raw: list[Claim],
    claims: list[Claim],
    by_statement: dict[str, str],
    next_index: int,
) -> tuple[dict[str, str], int, int]:
    """Assign global IDs, collapsing the same statement found twice.

    Returning the local→global map lets evidence rows in the same window keep
    pointing at the right claim after renumbering. The merged count is stored
    in the run trace so over-merging can be reviewed later.
    """

    id_map: dict[str, str] = {}
    merged = 0
    for claim in raw:
        key = _normalise_text(claim.statement)
        existing = by_statement.get(key)
        if existing is not None:
            id_map[claim.claim_id] = existing
            merged += 1
            continue
        new_id = f"claim-{next_index:03d}"
        next_index += 1
        by_statement[key] = new_id
        id_map[claim.claim_id] = new_id
        claims.append(_reset_claim(claim).model_copy(update={"claim_id": new_id}))
    return id_map, next_index, merged


def _merge_evidence(
    raw: list[EvidenceRecord],
    id_map: dict[str, str],
    source_ids: set[str],
    evidence: list[EvidenceRecord],
    seen: set[tuple[str, str, str, str]],
    next_index: int,
    non_verbatim: set[str] | None = None,
    locator_map: dict[str, str] | None = None,
) -> tuple[int, int]:
    dropped = 0
    flagged = non_verbatim or set()
    locators = locator_map or {}
    for record in raw:
        claim_id = id_map.get(record.claim_id)
        if claim_id is None or record.source_id not in source_ids:
            dropped += 1
            continue
        locator = record.locator.strip()
        if locator in locators:
            locator = locators[locator]
        else:
            match = re.search(r"source-[0-9]{3,}:b[0-9]{4,}", locator)
            if match and match.group(0) in locators:
                locator = locators[match.group(0)]
        key = (
            claim_id,
            record.source_id,
            _normalise_text(record.source_excerpt),
            _normalise_text(locator),
        )
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        new_id = f"evidence-{next_index:03d}"
        next_index += 1
        notes = record.notes
        if record.evidence_id in flagged:
            marker = "excerpt not verbatim in the source window"
            notes = f"{notes} | {marker}" if notes.strip() else marker
        evidence.append(
            _reset_evidence(record).model_copy(
                update={
                    "evidence_id": new_id,
                    "claim_id": claim_id,
                    "locator": locator,
                    "notes": notes,
                }
            )
        )
    return next_index, dropped


def _merge_elements(
    raw: list[PaperElementDraft],
    window: ChunkWindow,
    elements: list[PaperElement],
    seen: set[tuple[str, str, str]],
    next_index: int,
) -> int:
    for draft in raw:
        locator = draft.locator.strip() or window.locator
        key = (draft.kind, _normalise_text(draft.title), _normalise_text(locator))
        if key in seen:
            continue
        seen.add(key)
        elements.append(
            PaperElement(
                paper_item_id=f"paper-{next_index:03d}",
                kind=draft.kind,
                title=draft.title,
                locator=locator,
                required=draft.kind in _REQUIRED_ELEMENT_KINDS,
                status="unverified",
                notes=draft.notes,
            )
        )
        next_index += 1
    return next_index


def _derive_findings(claims: list[Claim], evidence: list[EvidenceRecord]) -> list[ResearchFinding]:
    by_claim: dict[str, list[str]] = {}
    for record in evidence:
        by_claim.setdefault(record.claim_id, []).append(record.evidence_id)
    return [
        ResearchFinding(
            claim_id=claim.claim_id,
            statement=claim.statement,
            evidence_ids=by_claim[claim.claim_id],
            confidence="medium",
        )
        for claim in claims
        if by_claim.get(claim.claim_id)
    ]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = _normalise_text(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def run_research(
    project_dir: Path,
    config: ProjectConfig,
    provider: ModelProvider,
    *,
    prompt_char_budget: int = 120_000,
    max_output_tokens: int | None = None,
) -> tuple[ResearchBrief, EvidenceLedger]:
    registry = load_registry(project_dir)
    if registry is None or not registry.sources:
        raise ValidationFailure("source registry is missing or empty; run `lces ingest` first")

    source_map = ensure_source_map(project_dir, config.project_id, registry)
    paper_map = load_paper_map(project_dir)
    records = {record.source_id: record for record in registry.sources}
    source_ids = set(records)

    claims: list[Claim] = []
    evidence: list[EvidenceRecord] = []
    elements: list[PaperElement] = []
    claim_by_statement: dict[str, str] = {}
    evidence_seen: set[tuple[str, str, str, str]] = set()
    element_seen: set[tuple[str, str, str]] = set()
    unknowns: list[str] = []
    limitations: list[str] = []
    conflicts: list[str] = []
    calls: list[dict[str, Any]] = []
    next_claim = next_evidence = next_paper = 1
    dropped_evidence = 0
    merged_claims = 0
    quote_audits: list[QuoteAudit] = []
    structured_audits: list[StructuredAudit] = []
    excluded_chunks: list[dict[str, str]] = []

    mapped_ids = {document.source_id for document in source_map.documents}
    for record in registry.sources:
        if record.source_id not in mapped_ids:
            unknowns.append(f"{record.source_id}: 无法提取正文，未参与研究")

    for document in source_map.documents:
        source_record = records.get(document.source_id)
        if source_record is None:
            continue
        teachable: list[SourceChunk] = []
        for chunk in document.chunks:
            if chunk.section and _EXCLUDED_SECTION.search(chunk.section):
                excluded_chunks.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "section": chunk.section,
                        "reason": "bibliography",
                    }
                )
            else:
                teachable.append(chunk)
        windows = _pack_windows(project_dir, document, prompt_char_budget, teachable)
        for window in windows:
            request = GenerationRequest(
                messages=[
                    Message("system", SECTION_PROMPT),
                    Message(
                        "user",
                        _window_prompt(config, source_record, window, paper_map),
                    ),
                ],
                max_tokens=max_output_tokens or DEFAULT_MAX_TOKENS,
                metadata={
                    "project_id": config.project_id,
                    "title": config.title,
                    "source_ids": document.source_id,
                    "chunk_ids": ",".join(window.chunk_ids),
                    "stage": "research",
                },
            )
            section = provider.generate_structured(request, SectionAnalysis)

            document_text = load_source_text(project_dir, document.source_id)
            chunk_map = {chunk.chunk_id: chunk for chunk in window.chunks}
            structured_records = [
                evidence_record
                for evidence_record in section.evidence
                if evidence_record.evidence_type in {"formula", "table"}
            ]
            quote_records = [
                evidence_record
                for evidence_record in section.evidence
                if evidence_record.evidence_type not in {"formula", "table"}
            ]
            candidates = [
                QuoteCandidate(
                    candidate_id=evidence_record.evidence_id,
                    claim_id=evidence_record.claim_id,
                    source_id=evidence_record.source_id,
                    chunk_id=evidence_record.chunk_id,
                    locator=evidence_record.locator,
                    text=evidence_record.source_excerpt,
                )
                for evidence_record in quote_records
            ]
            located, audit = validate_candidates(
                candidates,
                claim_ids={claim.claim_id for claim in section.claims},
                chunks=chunk_map,
                source_texts={document.source_id: document_text},
            )
            quote_audits.append(audit)

            accepted: list[EvidenceRecord] = []
            originals = {
                evidence_record.evidence_id: evidence_record for evidence_record in quote_records
            }
            for item in located:
                if item.location.status not in {"verified_exact", "verified_normalized"}:
                    continue
                original = originals.get(item.candidate.candidate_id)
                if original is None:
                    continue
                accepted.append(
                    original.model_copy(
                        update={
                            "source_excerpt": item.location.excerpt,
                            "locator": item.location.locator,
                            "chunk_id": item.location.chunk_id,
                            "quote_status": item.location.status,
                        }
                    )
                )

            structured_audit = StructuredAudit()
            for structured_record in structured_records:
                location = validate_structured_record(
                    structured_record,
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
                    accepted.append(
                        structured_record.model_copy(
                            update={
                                "source_excerpt": location.excerpt,
                                "locator": location.locator,
                                "chunk_id": location.chunk_id,
                                "quote_status": "verified_structured",
                            }
                        )
                    )
                elif location.status == "needs_review":
                    structured_audit.needs_review += 1
                    structured_audit.reviews.append(review_for(structured_record, location))
                else:
                    structured_audit.rejected += 1
                    structured_audit.reviews.append(review_for(structured_record, location))
            structured_audits.append(structured_audit)

            section = section.model_copy(update={"evidence": accepted})

            id_map, next_claim, merged = _merge_claims(
                section.claims, claims, claim_by_statement, next_claim
            )
            merged_claims += merged
            next_evidence, dropped = _merge_evidence(
                section.evidence,
                id_map,
                source_ids,
                evidence,
                evidence_seen,
                next_evidence,
            )
            dropped_evidence += dropped
            next_paper = _merge_elements(
                section.paper_elements, window, elements, element_seen, next_paper
            )
            unknowns.extend(section.unknowns)
            limitations.extend(section.limitations)
            conflicts.extend(section.source_conflicts)

            last = provider.last_result
            calls.append(
                {
                    "index": len(calls) + 1,
                    "source_id": document.source_id,
                    "chunk_ids": window.chunk_ids,
                    "section": window.section,
                    "pages": window.pages,
                    "provider": provider.name,
                    "model": provider.model,
                    "usage": last.usage.as_dict() if last else {},
                    "finish_reason": last.finish_reason if last else "",
                    "request_id": last.request_id if last else "",
                    "quote_audit": audit.model_dump(mode="json", exclude={"reviews"}),
                    "structured_audit": structured_audit.model_dump(
                        mode="json", exclude={"reviews"}
                    ),
                }
            )
            # Preserve progress after every completed window. A later window
            # can fail (timeout, truncation); the checkpoint still shows which
            # calls succeeded and what they produced.
            checkpoint_audit = merge_audits(quote_audits)
            checkpoint_structured = merge_structured_audits(structured_audits)
            write_json(
                project_dir / "internal" / "research_checkpoint.json",
                {
                    "project_id": config.project_id,
                    "updated_at": utc_now(),
                    "calls": calls,
                    "claims": claims,
                    "evidence": evidence,
                    "paper_elements": elements,
                    "excluded_chunks": excluded_chunks,
                    "merged_claims": merged_claims,
                    "quote_audit": checkpoint_audit.model_dump(mode="json"),
                    "structured_audit": checkpoint_structured.model_dump(mode="json"),
                    "non_verbatim_evidence": (
                        checkpoint_audit.needs_review + checkpoint_audit.rejected
                    ),
                },
            )

    quote_audit = merge_audits(quote_audits)
    structured_audit = merge_structured_audits(structured_audits)

    if not claims:
        raise ValidationFailure(
            "sectioned research produced no claims; refusing to continue with an empty brief"
        )

    paper_map_path = ""
    if elements:
        extracted = PaperMap(
            project_id=config.project_id,
            source_ids=sorted(source_ids),
            parser="sectioned-research/1",
            generated_at=utc_now(),
            elements=elements,
        )
        plan_dir = project_dir / "internal" / "plan"
        write_json(plan_dir / "paper_map.extracted.json", extracted)
        # A human-authored blueprint wins; machine findings stay alongside it
        # for reconciliation instead of silently replacing it.
        if not (plan_dir / "paper_map.json").exists():
            write_json(plan_dir / "paper_map.json", extracted)
            paper_map_path = "internal/plan/paper_map.json"

    analysis = ResearchAnalysis(
        research_question=f"{config.title}：核心问题、方法与可核验证据",
        scope=(
            f"分节研究：{len(source_map.documents)} 个来源，"
            f"{sum(len(document.chunks) for document in source_map.documents)} 个区块，"
            f"{len(calls)} 次模型调用"
        ),
        claims=claims,
        evidence=evidence,
        findings=_derive_findings(claims, evidence),
        unknowns=_unique(unknowns),
        source_conflicts=_unique(conflicts),
        limitations=_unique(limitations),
    )
    brief = ResearchBrief(
        project_id=config.project_id,
        research_question=analysis.research_question,
        scope=analysis.scope,
        findings=analysis.findings,
        unknowns=analysis.unknowns,
        source_conflicts=analysis.source_conflicts,
        limitations=analysis.limitations,
    )
    ledger = EvidenceLedger(project_id=config.project_id, records=evidence)

    _persist(
        project_dir,
        analysis,
        brief,
        ledger,
        provider,
        dropped_evidence,
        calls=calls,
        paper_map_path=paper_map_path,
        merged_claims=merged_claims,
        non_verbatim_evidence=quote_audit.needs_review + quote_audit.rejected,
        quote_audit=quote_audit,
        structured_audit=structured_audit,
        excluded_chunks=excluded_chunks,
    )
    return brief, ledger


def _reset_verification(analysis: ResearchAnalysis) -> ResearchAnalysis:
    """Drop model-reported review state; humans own the verification column."""

    return analysis.model_copy(
        update={
            "claims": [_reset_claim(claim) for claim in analysis.claims],
            "evidence": [_reset_evidence(record) for record in analysis.evidence],
        }
    )


def _persist(
    project_dir: Path,
    analysis: ResearchAnalysis,
    brief: ResearchBrief,
    ledger: EvidenceLedger,
    provider: ModelProvider,
    dropped_evidence: int,
    *,
    calls: list[dict[str, Any]] | None = None,
    paper_map_path: str = "",
    merged_claims: int = 0,
    non_verbatim_evidence: int = 0,
    quote_audit: QuoteAudit | None = None,
    structured_audit: StructuredAudit | None = None,
    excluded_chunks: list[dict[str, str]] | None = None,
) -> None:
    internal = project_dir / "internal"
    calls = calls or []
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for call in calls:
        call_usage = call.get("usage") or {}
        for name in totals:
            totals[name] += int(call_usage.get(name) or 0)
    usage = (
        totals if calls else (provider.last_result.usage.as_dict() if provider.last_result else {})
    )
    write_json(
        internal / "research_analysis.json",
        {
            "analysis": analysis,
            "provider": provider.name,
            "model": provider.model,
            "generated_at": utc_now(),
            "usage": usage,
            "research_calls": calls,
            "paper_map": paper_map_path,
            "merged_claims": merged_claims,
            "non_verbatim_evidence": non_verbatim_evidence,
            "quote_audit": (
                quote_audit.model_dump(mode="json", exclude={"reviews"}) if quote_audit else {}
            ),
            "structured_audit": (
                structured_audit.model_dump(mode="json", exclude={"reviews"})
                if structured_audit
                else {}
            ),
            "excluded_chunks": excluded_chunks or [],
            "dropped_evidence": dropped_evidence,
        },
    )
    if quote_audit is not None:
        write_json(internal / "qa" / "quote_audit.json", quote_audit)
    if structured_audit is not None:
        write_json(internal / "qa" / "structured_evidence_audit.json", structured_audit)
    write_json(internal / "claims.json", analysis.claims)
    write_json(internal / "research_brief.json", brief)
    write_evidence_csv(internal / "evidence_ledger.csv", ledger)
    write_text(internal / "research_brief.md", render_brief_markdown(brief, ledger))


def _structured_json(record: EvidenceRecord) -> str:
    payload: dict[str, object] = {}
    if record.formula is not None:
        payload["formula"] = record.formula.model_dump(mode="json")
    if record.table is not None:
        payload["table"] = record.table.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False) if payload else ""


def _structured_field(raw: str, name: str):
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    value = payload.get(name) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else None


def write_evidence_csv(path: Path, ledger: EvidenceLedger) -> Path:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EVIDENCE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in ledger.records:
        writer.writerow(
            {
                "evidence_id": record.evidence_id,
                "source_id": record.source_id,
                "chunk_id": record.chunk_id,
                "claim_id": record.claim_id,
                "evidence_type": record.evidence_type,
                "locator": record.locator,
                "source_excerpt": record.source_excerpt,
                "support_relation": record.support_relation,
                "verification_status": record.verification_status,
                "quote_status": record.quote_status,
                "structured_json": _structured_json(record),
                "reviewer": record.reviewer,
                "checked_at": record.checked_at.isoformat() if record.checked_at else "",
                "notes": record.notes,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig keeps Excel usable on Windows; readers must use utf-8-sig.
    path.write_text(buffer.getvalue(), encoding="utf-8-sig", newline="")
    return path


def load_evidence_ledger(project_dir: Path) -> EvidenceLedger:
    path = project_dir / "internal" / "evidence_ledger.csv"
    records: list[EvidenceRecord] = []
    if not path.exists():
        return EvidenceLedger(project_id="", records=[])
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("evidence_id"):
                continue
            checked = row.get("checked_at") or None
            records.append(
                EvidenceRecord.model_validate(
                    {
                        "evidence_id": row["evidence_id"],
                        "source_id": row.get("source_id", ""),
                        "chunk_id": row.get("chunk_id") or "",
                        "claim_id": row.get("claim_id", ""),
                        "evidence_type": row.get("evidence_type") or "analysis",
                        "locator": row.get("locator") or "",
                        "source_excerpt": row.get("source_excerpt") or "",
                        "support_relation": row.get("support_relation") or "background",
                        "verification_status": row.get("verification_status") or "unverified",
                        "quote_status": row.get("quote_status") or "unverified",
                        "formula": _structured_field(row.get("structured_json") or "", "formula"),
                        "table": _structured_field(row.get("structured_json") or "", "table"),
                        "reviewer": row.get("reviewer") or "",
                        "checked_at": checked,
                        "notes": row.get("notes") or "",
                    }
                )
            )
    return EvidenceLedger(project_id="", records=records)


def load_research_brief(project_dir: Path) -> ResearchBrief | None:
    path = project_dir / "internal" / "research_brief.json"
    if not path.exists():
        return None
    try:
        return ResearchBrief.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def render_brief_markdown(brief: ResearchBrief, ledger: EvidenceLedger) -> str:
    lines = [
        f"# 研究简报（内部）：{brief.project_id}",
        "",
        "> 内部工作材料，不得进入公开页面或正式交付包。",
        "",
        "## 研究问题",
        "",
        brief.research_question,
        "",
        "## 范围",
        "",
        brief.scope,
        "",
        "## 关键发现",
        "",
    ]
    if not brief.findings:
        lines.append("（未生成可追踪的发现）")
    for finding in brief.findings:
        lines.append(f"### {finding.claim_id}（置信度：{finding.confidence}）")
        lines.append("")
        lines.append(finding.statement)
        if finding.evidence_ids:
            lines.append(f"证据: {', '.join(finding.evidence_ids)}")
        if finding.limitations:
            lines.append(f"限制: {finding.limitations}")
        lines.append("")

    lines += ["## 未知项", ""]
    lines += [f"- {item}" for item in brief.unknowns] or ["- （无）"]
    lines += ["", "## 来源冲突", ""]
    lines += [f"- {item}" for item in brief.source_conflicts] or ["- （未发现或未检查）"]
    lines += ["", "## 研究限制", ""]
    lines += [f"- {item}" for item in brief.limitations] or ["- （无）"]

    lines += [
        "",
        "## 证据台账",
        "",
        "| evidence | source | claim | 关系 | 核验 |",
        "|---|---|---|---|---|",
    ]
    for record in ledger.records:
        lines.append(
            f"| {record.evidence_id} | {record.source_id} | {record.claim_id} |"
            f" {record.support_relation} | {record.verification_status} |"
        )
    lines.append("")
    return "\n".join(lines)
