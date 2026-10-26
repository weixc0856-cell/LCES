"""Evidence-constrained expansion of one LearningUnit's narration.

The model may only explain what the unit's claims and evidence already support.
The program rejects an expansion that invents numbers, drops the visual sync,
falls short of the duration budget, or repeats itself. Nothing is written until
the provider output and every deterministic check pass.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from content_studio.content import (
    NARRATION_CHARS_PER_SECOND,
    estimate_narration_seconds,
    render_script_markdown,
)
from content_studio.errors import ValidationFailure
from content_studio.models import (
    Claim,
    EvidenceLedger,
    LearningUnit,
    ProjectConfig,
    PublicSlide,
    ScriptSection,
    SpeakerScript,
    StrictModel,
)
from content_studio.providers.base import (
    DEFAULT_MAX_TOKENS,
    GenerationRequest,
    GenerationResult,
    Message,
    ModelProvider,
)
from content_studio.utils import utc_now_iso, write_json, write_text

ExpansionKind = Literal[
    "concept",
    "derivation",
    "evidence",
    "example",
    "visual_sync",
    "limitation",
    "transition",
]
SYNC_BLOCKS = {"formula", "table", "interactive", "svg", "figure", "chart", "diagram", "graph"}
NUMBER = re.compile(r"(?<![\w.-])\d+(?:\.\d+)?")
INTERNAL_ID = re.compile(r"\b(?:evidence|claim|paper|unit|slide)-\d+")
SENTENCE_SPLIT = re.compile(r"[。！？!?]")


class VisualSync(StrictModel):
    block: int = Field(ge=0)
    note: str = Field(min_length=1)


class UnitExpansion(StrictModel):
    unit_id: str = Field(min_length=1)
    narration: str = Field(min_length=1)
    kinds: list[ExpansionKind] = Field(default_factory=list)
    claims_used: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    visual_sync: list[VisualSync] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ExpansionResult:
    unit_id: str
    scene_id: str
    before_chars: int
    after_chars: int
    before_seconds: int
    after_seconds: int
    budget_seconds: int
    claims_used: tuple[str, ...]
    evidence_used: tuple[str, ...]
    kinds: tuple[str, ...]
    visual_sync_blocks: tuple[int, ...]
    stripped_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "scene_id": self.scene_id,
            "before_chars": self.before_chars,
            "after_chars": self.after_chars,
            "before_seconds": self.before_seconds,
            "after_seconds": self.after_seconds,
            "budget_seconds": self.budget_seconds,
            "claims_used": list(self.claims_used),
            "evidence_used": list(self.evidence_used),
            "kinds": list(self.kinds),
            "visual_sync_blocks": list(self.visual_sync_blocks),
            "stripped_ids": list(self.stripped_ids),
        }


def _block_summary(slide: PublicSlide) -> list[str]:
    lines: list[str] = []
    for index, block in enumerate(slide.body):
        detail = (
            getattr(block, "text", "")
            or getattr(block, "title", "")
            or getattr(block, "caption", "")
            or getattr(block, "alt", "")
            or getattr(block, "label", "")
            or ""
        )
        lines.append(f"[{index}] {block.type}: {' '.join(str(detail).split())[:120]}")
    return lines


def _evidence_context(
    unit: LearningUnit,
    ledger: EvidenceLedger | None,
    claims: list[Claim] | None,
) -> tuple[str, dict[str, str], dict[str, str]]:
    claim_text = {claim.claim_id: claim.statement for claim in claims or []}
    evidence_text: dict[str, str] = {}
    if ledger is not None:
        for record in ledger.records:
            if record.evidence_id in unit.evidence_ids:
                excerpt = " ".join(record.source_excerpt.split())[:400]
                evidence_text[record.evidence_id] = excerpt
                if record.claim_id and record.claim_id not in claim_text:
                    claim_text[record.claim_id] = ""
    lines = []
    for claim_id in unit.claim_ids:
        statement = claim_text.get(claim_id, "")
        if statement:
            lines.append(f"- claim {claim_id}: {statement}")
    for evidence_id in unit.evidence_ids:
        excerpt = evidence_text.get(evidence_id, "")
        if excerpt:
            lines.append(f"- evidence {evidence_id}: {excerpt}")
    return "\n".join(lines)[:12_000], claim_text, evidence_text


def _allowed_numbers(texts: list[str]) -> set[str]:
    allowed: set[str] = set()
    for text in texts:
        allowed.update(NUMBER.findall(text))
    return allowed


def _strip_internal_ids(text: str) -> tuple[str, list[str]]:
    """Remove internal identifiers from spoken text, keeping neutral wording."""

    removed = INTERNAL_ID.findall(text)
    if not removed:
        return text, []
    text = re.sub(r"\bclaim-\d+\b", "已有主张", text)
    text = re.sub(r"\bevidence-\d+\b", "已有证据", text)
    text = re.sub(r"\bpaper-\d+\b", "论文", text)
    text = re.sub(r"\bunit-\d+\b", "本单元", text)
    text = re.sub(r"\bslide-\d+\b", "本节", text)
    text = text.replace("论文 论文", "论文")
    text = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)
    text = re.sub(r"\s+([，。；！？、])", r"", text)
    text = re.sub(r"[ 	]{2,}", " ", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。！？]{2,}", "。", text)
    return text, removed


def _validate(
    expansion: UnitExpansion,
    unit: LearningUnit,
    slide: PublicSlide,
    current_narration: str,
    budget_seconds: int,
    claim_text: dict[str, str],
    evidence_text: dict[str, str],
) -> None:
    if expansion.unit_id != unit.unit_id:
        raise ValidationFailure(
            f"expander returned {expansion.unit_id} while expanding {unit.unit_id}"
        )
    if not expansion.kinds:
        raise ValidationFailure("expansion does not say what kind of explanation it added")
    leaked = INTERNAL_ID.findall(expansion.narration)
    if leaked:
        raise ValidationFailure(
            "narration contains internal ids that must not be spoken: " + ", ".join(leaked)
        )
    known_claims = set(claim_text)
    unknown_claims = [item for item in expansion.claims_used if item not in known_claims]
    if unknown_claims:
        raise ValidationFailure("expansion cites unknown claims: " + ", ".join(unknown_claims))
    known_evidence = set(evidence_text)
    unknown_evidence = [item for item in expansion.evidence_used if item not in known_evidence]
    if unknown_evidence:
        raise ValidationFailure(
            "expansion cites evidence outside this unit: " + ", ".join(unknown_evidence)
        )
    if (unit.claim_ids or unit.evidence_ids) and not (
        expansion.claims_used or expansion.evidence_used
    ):
        raise ValidationFailure("expansion cites no claim or evidence from this unit")

    block_indexes = {item.block for item in expansion.visual_sync}
    for block in block_indexes:
        if block >= len(slide.body):
            raise ValidationFailure(f"visual_sync points at missing block {block}")
    required = {index for index, item in enumerate(slide.body) if item.type in SYNC_BLOCKS}
    missing = sorted(required - block_indexes)
    if required and missing:
        raise ValidationFailure(
            "expansion does not explain these visual blocks: " + ", ".join(map(str, missing))
        )

    target_chars = int(round(budget_seconds * NARRATION_CHARS_PER_SECOND))
    length = len(expansion.narration)
    if length < max(len(current_narration), int(target_chars * 0.75)):
        raise ValidationFailure(
            f"expansion is too short for the budget: {length} chars, "
            f"current {len(current_narration)}, target ~{target_chars}"
        )
    if length > int(target_chars * 1.35):
        raise ValidationFailure(
            f"expansion exceeds the budget by more than 35%: {length} chars, target ~{target_chars}"
        )

    sentences = [
        sentence.strip()
        for sentence in SENTENCE_SPLIT.split(expansion.narration)
        if len(sentence.strip()) >= 10
    ]
    seen: set[str] = set()
    for sentence in sentences:
        if sentence in seen:
            raise ValidationFailure("expansion repeats a sentence: " + sentence[:40])
        seen.add(sentence)

    allowed = _allowed_numbers(
        [
            current_narration,
            *claim_text.values(),
            *evidence_text.values(),
            *[str(getattr(block, "text", "")) for block in slide.body],
            *[str(getattr(block, "caption", "")) for block in slide.body],
            unit.title,
            *unit.objectives,
            *unit.key_concepts,
        ]
    )
    unsupported = sorted(set(NUMBER.findall(expansion.narration)) - allowed)
    if unsupported:
        raise ValidationFailure(
            "expansion states numbers that are not in its evidence: " + ", ".join(unsupported)
        )


def _write_section(
    project_dir: Path,
    config: ProjectConfig,
    script: SpeakerScript,
    outline,
    section: ScriptSection,
) -> SpeakerScript:
    sections = [section if item.slide_id == section.slide_id else item for item in script.sections]
    updated = script.model_copy(
        update={
            "sections": sections,
            "total_estimated_seconds": sum(item.estimated_seconds for item in sections),
        }
    )
    path = project_dir / "internal" / "speaker_script.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for position, item in enumerate(raw.get("sections", [])):
        if item.get("slide_id") == section.slide_id:
            raw["sections"][position] = section.model_dump(mode="json")
            break
    raw["total_estimated_seconds"] = updated.total_estimated_seconds
    write_json(path, raw)
    write_text(
        project_dir / "internal" / "speaker_script.md",
        render_script_markdown(updated, outline, config),
    )
    return updated


def _log_rejection(
    project_dir: Path,
    unit: LearningUnit,
    provider: ModelProvider,
    expansion: UnitExpansion,
    reason: str,
) -> None:
    path = project_dir / "internal" / "qa" / "expansion_rejected.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "unit_id": unit.unit_id,
        "reason": reason,
        "provider": provider.name,
        "model": provider.model,
        "expansion": expansion.model_dump(mode="json"),
        "raw": (provider.last_result.text if provider.last_result else "")[:20_000],
        "generated_at": utc_now_iso(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_expansion(project_dir: Path, result: ExpansionResult, provider: ModelProvider) -> None:
    path = project_dir / "internal" / "qa" / "unit_expansions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        **result.as_dict(),
        "provider": provider.name,
        "model": provider.model,
        "generated_at": utc_now_iso(),
        "method": "evidence_constrained_expansion",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _merge_expansions(base: UnitExpansion, extra: UnitExpansion) -> UnitExpansion:
    """Append a repair paragraph and merge its sync/evidence fields."""

    left = base.narration.rstrip()
    if left and left[-1] not in "。！？!?":
        left += "。"
    sync = {item.block: item for item in base.visual_sync}
    sync.update({item.block: item for item in extra.visual_sync})
    return UnitExpansion(
        unit_id=base.unit_id,
        narration=left + extra.narration.strip(),
        kinds=list(dict.fromkeys([*base.kinds, *extra.kinds])),
        claims_used=list(dict.fromkeys([*base.claims_used, *extra.claims_used])),
        evidence_used=list(dict.fromkeys([*base.evidence_used, *extra.evidence_used])),
        visual_sync=sorted(sync.values(), key=lambda item: item.block),
        uncertainty_notes=[*base.uncertainty_notes, *extra.uncertainty_notes],
    )


def expand_unit(
    project_dir: Path,
    config: ProjectConfig,
    unit: LearningUnit,
    slide: PublicSlide,
    script: SpeakerScript,
    outline,
    ledger: EvidenceLedger | None,
    claims: list[Claim] | None,
    budget_seconds: int,
    provider: ModelProvider,
    *,
    max_tokens: int | None = None,
    expansion_override: UnitExpansion | None = None,
) -> ExpansionResult:
    section = next((item for item in script.sections if item.slide_id == slide.slide_id), None)
    if section is None:
        raise ValidationFailure(f"speaker script has no section for {slide.slide_id}")
    current = section.narration
    target_chars = int(round(budget_seconds * NARRATION_CHARS_PER_SECOND))
    evidence_context, claim_text, evidence_text = _evidence_context(unit, ledger, claims)
    evidence_hint = evidence_context or (
        "（本单元没有登记证据；只能解释已有讲稿与视觉内容，不得新增事实）"
    )
    minimum_chars = max(len(current), int(target_chars * 0.75))
    blocks = "\n".join(_block_summary(slide))
    prompt = (
        f"项目: {config.title}（{config.project_id}）\n"
        f"语言: {config.language}；受众: {config.audience}\n\n"
        f"教学单元: {unit.unit_id}《{unit.title}》\n"
        f"学习目标: {'；'.join(unit.objectives) or '未提供'}\n"
        f"关键概念: {'；'.join(unit.key_concepts) or '未提供'}\n"
        f"口播预算: {budget_seconds} 秒，约 {target_chars} 字（4.2 字/秒）\n\n"
        "本单元可用的主张与证据（只能使用这些事实）:\n"
        f"{evidence_hint}\n\n"
        "当前讲稿（保留有效内容，补充缺失的教学解释；不要逐句重复）:\n"
        f"{current}\n\n"
        "场景中的视觉元素:\n"
        f"{blocks}\n\n"
        "要求:\n"
        "1. 只补充真实的教学解释：概念定义、推导中间步骤、证据解读、必要例子、边界与过渡。\n"
        "2. 事实必须能由上面的主张/证据或当前讲稿支持；类比和示意例子要明确写成类比/示意。\n"
        "3. 不得新增证据中没有的数字、单位、实验结果或论文结论。\n"
        "4. 为每个公式/表格/实验/结构图 block 写一条 visual_sync，说明口播如何对应画面。\n"
        "5. 结尾形成结论，并自然过渡到下一单元。\n"
        "6. 不要为了凑时长重复结论、堆砌定义或写空泛开场白。\n"
        f"7. 目标长度约 {target_chars} 字，不得少于 {minimum_chars} 字；不足会被拒绝。\n\n"
        "写作结构（至少 4 段，每段 70–120 字）:\n"
        "1. 承接上一单元，点出本单元要解决的问题。\n"
        "2. 解释第一个视觉元素（公式/图/表）的含义与作用。\n"
        "3. 解释其余视觉元素，展开机制或推导的中间步骤。\n"
        "4. 说明边界、常见误解或不确定性。\n"
        "5. 形成结论并过渡到下一单元。\n"
        "输出前自检 narration 字数；不足则继续补充解释，不要提前结束。\n\n"
        "返回结构示例（只示范字段形状，内容不要照抄）:\n"
        '{"unit_id":"unit-105","narration":"……","kinds":["concept","visual_sync"],'
        '"claims_used":["claim-..."],"evidence_used":["evidence-..."],'
        '"visual_sync":[{"block":1,"note":"……"},{"block":3,"note":"……"}],'
        '"uncertainty_notes":[]}\n'
        "返回 UnitExpansion。"
    )
    if provider.name == "local":
        prompt += "\n/no_think"
    request = GenerationRequest(
        messages=[Message("system", EXPANSION_SYSTEM), Message("user", prompt)],
        max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
        metadata={
            "project_id": config.project_id,
            "title": config.title,
            "unit_id": unit.unit_id,
            "slide_id": slide.slide_id,
            "budget_seconds": str(budget_seconds),
            "required_blocks": ",".join(
                str(index) for index, block in enumerate(slide.body) if block.type in SYNC_BLOCKS
            ),
            "claim_ids": ",".join(unit.claim_ids),
            "evidence_ids": ",".join(unit.evidence_ids),
            "stage": "unit_expansion",
        },
    )
    if expansion_override is None:
        expansion = provider.generate_structured(request, UnitExpansion)
    else:
        expansion = expansion_override
    stripped_ids: list[str] = []
    required = {index for index, block in enumerate(slide.body) if block.type in SYNC_BLOCKS}
    for attempt in range(3):
        cleaned, removed = _strip_internal_ids(expansion.narration)
        stripped_ids.extend(removed)
        if removed:
            expansion = expansion.model_copy(update={"narration": cleaned})
        try:
            _validate(
                expansion,
                unit,
                slide,
                current,
                budget_seconds,
                claim_text,
                evidence_text,
            )
            break
        except ValidationFailure as exc:
            if attempt == 2:
                _log_rejection(project_dir, unit, provider, expansion, str(exc))
                raise
            missing = sorted(required - {item.block for item in expansion.visual_sync})
            remaining = max(80, minimum_chars - len(expansion.narration))
            correction = GenerationRequest(
                messages=[
                    Message("system", EXPANSION_SYSTEM),
                    Message(
                        "user",
                        "现有讲稿：\n"
                        + expansion.narration
                        + "\n\n上一次输出未通过检查："
                        + str(exc)
                        + "\n请只补充缺失内容（不要重复已有句子），新增约 "
                        + str(remaining)
                        + " 字，并确保 visual_sync 覆盖这些 block："
                        + (str(missing) if missing else "无")
                        + "。\nnarration 只包含新增段落；返回 UnitExpansion。",
                    ),
                ],
                max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                metadata=request.metadata,
            )
            extra = provider.generate_structured(correction, UnitExpansion)
            expansion = _merge_expansions(expansion, extra)
    new_section = section.model_copy(
        update={
            "narration": expansion.narration,
            "estimated_seconds": estimate_narration_seconds(expansion.narration),
        }
    )
    _write_section(project_dir, config, script, outline, new_section)
    result = ExpansionResult(
        unit_id=unit.unit_id,
        scene_id=slide.slide_id,
        before_chars=len(current),
        after_chars=len(expansion.narration),
        before_seconds=section.estimated_seconds,
        after_seconds=new_section.estimated_seconds,
        budget_seconds=budget_seconds,
        claims_used=tuple(expansion.claims_used),
        evidence_used=tuple(expansion.evidence_used),
        kinds=tuple(expansion.kinds),
        visual_sync_blocks=tuple(sorted({item.block for item in expansion.visual_sync})),
        stripped_ids=tuple(stripped_ids),
    )
    _log_expansion(project_dir, result, provider)
    return result


EXPANSION_SYSTEM = """你是课程讲稿编辑，只做有证据约束的教学扩展。
你可以解释、推导、连接和标注不确定性，但不能创造论文事实、数字或结论。
口播正文绝对不能出现 evidence-/claim-/paper-/unit-/slide- 编号；需要指代来源时
用“论文的 Table 2”“这个公式”“摘要”等自然说法，编号只放在 claims_used/evidence_used。
类比、示意和假设必须明确标记；不确定的内容写进 uncertainty_notes。
返回严格符合 UnitExpansion 的 JSON。"""


class ProvidedProvider(ModelProvider):
    """Marker for an expansion supplied as JSON; the guards still run."""

    name = "provided"
    model = "authored-json"

    def generate(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise AssertionError("a provided expansion is not generated by a model")
