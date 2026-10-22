"""Research and evidence governance (Skill: knowledge-learning-studio)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from content_studio.errors import ValidationFailure
from content_studio.ingestion import load_registry, load_source_text
from content_studio.models import (
    EvidenceLedger,
    EvidenceRecord,
    ProjectConfig,
    ResearchAnalysis,
    ResearchBrief,
    SourceRegistry,
)
from content_studio.providers.base import GenerationRequest, Message, ModelProvider
from content_studio.utils import truncate, utc_now, write_json, write_text

EVIDENCE_COLUMNS = [
    "evidence_id",
    "source_id",
    "claim_id",
    "evidence_type",
    "locator",
    "source_excerpt",
    "support_relation",
    "verification_status",
    "reviewer",
    "checked_at",
    "notes",
]

SYSTEM_PROMPT = """你是 LCES 的研究与证据治理模块（knowledge-learning-studio）。
规则：
1. 只使用用户提供的来源文本，不得补写来源中没有的数据、页码、DOI 或实验结果。
2. 区分事实、推断、假设、未知与争议；不得把推断写成来源原文。
3. 每条 evidence 必须指向真实存在的 source_id 与 claim_id，locator 使用页码、章节或段落位置。
4. source_excerpt 必须是来源中的短摘录（不超过 200 字）；无法摘录时留空并在 notes 说明。
5. verification_status 默认为 unverified；只有来源文本明确支持时才可标为 verified。
6. ID 格式固定：claim-001、evidence-001；source_id 使用输入中给出的编号。
7. 来源不可用时，将其写入 unknowns，不得假装已阅读。
只输出符合给定 JSON Schema 的 JSON。"""


def _source_block(registry: SourceRegistry, project_dir: Path, budget: int) -> str:
    if not registry.sources:
        return "（没有来源）"
    per_source = max(2000, budget // len(registry.sources))
    chunks: list[str] = []
    for source in registry.sources:
        text = load_source_text(project_dir, source.source_id)
        header = (
            f"### {source.source_id}\n"
            f"标题: {source.title}\n"
            f"类型: {source.kind}\n"
            f"来源: {source.origin}\n"
            f"获取状态: {source.access_status}\n"
        )
        if source.notes:
            header += f"备注: {source.notes}\n"
        if not text:
            body = "（未能提取正文；不得推测其内容）"
        else:
            body = truncate(text, per_source)
        chunks.append(header + "\n" + body)
    return "\n\n".join(chunks)


def run_research(
    project_dir: Path,
    config: ProjectConfig,
    provider: ModelProvider,
    *,
    prompt_char_budget: int = 120_000,
) -> tuple[ResearchBrief, EvidenceLedger]:
    registry = load_registry(project_dir)
    if registry is None or not registry.sources:
        raise ValidationFailure("source registry is missing or empty; run `lces ingest` first")

    user_prompt = (
        f"项目: {config.title}（{config.project_id}）\n"
        f"任务类型: {config.content_mode}\n"
        f"受众: {config.audience}\n"
        f"目标语言: {config.language}\n\n"
        "请从以下来源中提取关键主张、证据、未知项与限制。\n\n"
        + _source_block(registry, project_dir, prompt_char_budget)
    )
    request = GenerationRequest(
        messages=[
            Message("system", SYSTEM_PROMPT),
            Message("user", user_prompt),
        ],
        metadata={
            "project_id": config.project_id,
            "title": config.title,
            "source_ids": ",".join(source.source_id for source in registry.sources),
            "stage": "research",
        },
    )
    analysis = provider.generate_structured(request, ResearchAnalysis)
    # A model cannot verify its own output: any status it reports is reset and
    # only a human reviewer (`lces review-claims`) may change it.
    analysis = _reset_verification(analysis)

    source_ids = {source.source_id for source in registry.sources}
    claim_ids = {claim.claim_id for claim in analysis.claims}
    kept = [
        evidence
        for evidence in analysis.evidence
        if evidence.source_id in source_ids and evidence.claim_id in claim_ids
    ]
    dropped = len(analysis.evidence) - len(kept)
    if dropped:
        analysis = analysis.model_copy(update={"evidence": kept})

    brief = ResearchBrief(
        project_id=config.project_id,
        research_question=analysis.research_question,
        scope=analysis.scope,
        findings=[finding for finding in analysis.findings if finding.claim_id in claim_ids],
        unknowns=analysis.unknowns,
        source_conflicts=analysis.source_conflicts,
        limitations=analysis.limitations,
    )
    ledger = EvidenceLedger(project_id=config.project_id, records=kept)

    _persist(project_dir, analysis, brief, ledger, provider, dropped)
    return brief, ledger


def _reset_verification(analysis: ResearchAnalysis) -> ResearchAnalysis:
    """Drop model-reported review state; humans own the verification column."""

    claims = [
        claim.model_copy(
            update={"verification_status": "pending", "reviewer": "", "reviewed_at": None}
        )
        for claim in analysis.claims
    ]
    evidence = [
        record.model_copy(
            update={"verification_status": "unverified", "reviewer": "", "checked_at": None}
        )
        for record in analysis.evidence
    ]
    return analysis.model_copy(update={"claims": claims, "evidence": evidence})


def _persist(
    project_dir: Path,
    analysis: ResearchAnalysis,
    brief: ResearchBrief,
    ledger: EvidenceLedger,
    provider: ModelProvider,
    dropped_evidence: int,
) -> None:
    internal = project_dir / "internal"
    usage = provider.last_result.usage.as_dict() if provider.last_result else {}
    write_json(
        internal / "research_analysis.json",
        {
            "analysis": analysis,
            "provider": provider.name,
            "model": provider.model,
            "generated_at": utc_now(),
            "usage": usage,
            "dropped_evidence": dropped_evidence,
        },
    )
    write_json(internal / "claims.json", analysis.claims)
    write_json(internal / "research_brief.json", brief)
    write_evidence_csv(internal / "evidence_ledger.csv", ledger)
    write_text(internal / "research_brief.md", render_brief_markdown(brief, ledger))


def write_evidence_csv(path: Path, ledger: EvidenceLedger) -> Path:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EVIDENCE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in ledger.records:
        writer.writerow(
            {
                "evidence_id": record.evidence_id,
                "source_id": record.source_id,
                "claim_id": record.claim_id,
                "evidence_type": record.evidence_type,
                "locator": record.locator,
                "source_excerpt": record.source_excerpt,
                "support_relation": record.support_relation,
                "verification_status": record.verification_status,
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
                        "claim_id": row.get("claim_id", ""),
                        "evidence_type": row.get("evidence_type") or "analysis",
                        "locator": row.get("locator") or "",
                        "source_excerpt": row.get("source_excerpt") or "",
                        "support_relation": row.get("support_relation") or "background",
                        "verification_status": row.get("verification_status") or "unverified",
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
