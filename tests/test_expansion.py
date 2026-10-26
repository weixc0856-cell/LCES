"""Evidence-constrained unit expansion: validation, sanitising, atomic writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio.errors import ValidationFailure
from content_studio.expansion import expand_unit
from content_studio.models import (
    CheckBlock,
    Claim,
    ContentOutline,
    EvidenceLedger,
    EvidenceRecord,
    FormulaBlock,
    OutlineSection,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    ScriptSection,
    SpeakerScript,
)
from content_studio.paths import ensure_project_layout
from content_studio.providers.base import GenerationRequest, GenerationResult, ModelProvider
from content_studio.units import materialize_course
from content_studio.utils import write_json

SENTENCES = [
    "这一段先承接上一单元留下的问题并说明本单元要解决什么。",
    "位置编码把顺序信息写进向量而不是依赖循环结构来记住顺序。",
    "正弦与余弦的波长随维度变化使不同维度关注不同的距离尺度。",
    "公式里的偏移量决定旋转角度因此相对位置可以线性表达。",
    "频率随维度指数下降让高维通道记录更慢变化的模式。",
    "把位置向量加到词向量上不会改变维度也不会引入额外参数。",
    "论文选择固定编码而不是学习编码是为了外推到更长序列。",
    "需要说明这只是一种设计选择并不证明所有任务都更优。",
    "如果序列长度远超训练分布位置编码的外推仍然有限。",
    "最后把这一点与下一单元的注意力计算连接起来形成过渡。",
    "注意力本身不包含顺序信息因此需要额外的位置信号。",
    "正弦编码的每个维度对应不同频率形成多尺度表示。",
    "这种表示允许模型通过线性变换推断相对位移。",
    "固定编码不随训练更新因此不会占用模型容量。",
    "论文没有声称它优于所有可学习的位置表示。",
    "在超长序列上外推能力仍然需要实验验证。",
]


def _narration(sentences: int = 16) -> str:
    return "".join(SENTENCES[:sentences])


def _payload(**overrides):
    values = {
        "unit_id": "unit-101",
        "narration": _narration(),
        "kinds": ["concept", "visual_sync", "limitation"],
        "claims_used": ["claim-001"],
        "evidence_used": ["evidence-001"],
        "visual_sync": [{"block": 1, "note": "讲到公式时高亮维度与频率"}],
        "uncertainty_notes": [],
    }
    values.update(overrides)
    return values


class StubProvider(ModelProvider):
    name = "stub"
    model = "stub-1"

    def __init__(self, payload: dict):
        self._payload = payload

    def generate(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise AssertionError("expansion uses structured output")

    def generate_structured(self, request: GenerationRequest, schema):
        return schema.model_validate(self._payload)


def _project(tmp_path: Path):
    root = ensure_project_layout(tmp_path / "project")
    content = PublicContent(
        project_id="expand-demo",
        title="扩展测试课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="位置编码",
                body=[
                    ParagraphBlock(text="位置编码把顺序写进向量。"),
                    FormulaBlock(latex="PE(pos,2i)=sin(pos/10000^(2i/d))"),
                    CheckBlock(question="为什么需要位置编码？", answer="注意力本身无序。"),
                ],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-002",
                title="下一单元",
                body=[ParagraphBlock(text="保持不变的相邻单元。")],
                source_ids=["source-001"],
            ),
        ],
    )
    outline = ContentOutline(
        project_id="expand-demo",
        title="扩展测试课程",
        sections=[
            OutlineSection(
                slide_id="slide-001",
                title="位置编码",
                learning_objectives=["解释位置编码的作用"],
                key_points=["正弦", "频率", "相对位置"],
                evidence_ids=["evidence-001"],
                estimated_minutes=2.0,
            ),
            OutlineSection(
                slide_id="slide-002",
                title="下一单元",
                learning_objectives=["过渡"],
                evidence_ids=[],
                estimated_minutes=1.0,
            ),
        ],
        total_minutes=3.0,
    )
    script = SpeakerScript(
        project_id="expand-demo",
        sections=[
            ScriptSection(
                slide_id="slide-001",
                narration="位置编码把顺序写进向量，这是当前讲稿。",
                estimated_seconds=45,
            ),
            ScriptSection(
                slide_id="slide-002",
                narration="相邻单元保持原样。",
                estimated_seconds=20,
            ),
        ],
        total_estimated_seconds=65,
    )
    ledger = EvidenceLedger(
        project_id="expand-demo",
        records=[
            EvidenceRecord(
                evidence_id="evidence-001",
                source_id="source-001",
                chunk_id="source-001:b0000",
                claim_id="claim-001",
                evidence_type="quote",
                locator="§3.5",
                source_excerpt="We use sine and cosine functions of different frequencies.",
                support_relation="supports",
            )
        ],
    )
    claims = [
        Claim(claim_id="claim-001", statement="位置编码使用不同频率的正弦余弦", claim_type="fact")
    ]
    write_json(root / "content" / "public_content.json", content)
    write_json(root / "content" / "outline.json", outline)
    write_json(root / "internal" / "speaker_script.json", script)
    master = materialize_course(
        content, outline=outline, script=script, ledger=ledger, claims=claims
    )
    unit = next(item for item in master.units if item.unit_id == "unit-101")
    config = ProjectConfig(project_id="expand-demo", title="扩展测试课程")
    return root, config, content, unit, script, outline, ledger, claims


def _expand(root, config, content, unit, script, outline, ledger, claims, payload):
    slide = next(item for item in content.slides if item.slide_id == "slide-001")
    return expand_unit(
        root,
        config,
        unit,
        slide,
        script,
        outline,
        ledger,
        claims,
        120,
        StubProvider(payload),
    )


def test_expansion_replaces_only_its_section_and_logs_evidence(tmp_path):
    root, config, content, unit, script, outline, ledger, claims = _project(tmp_path)

    result = _expand(root, config, content, unit, script, outline, ledger, claims, _payload())

    assert result.before_chars == len("位置编码把顺序写进向量，这是当前讲稿。")
    assert result.after_chars == len(_narration())
    assert result.claims_used == ("claim-001",)
    assert result.evidence_used == ("evidence-001",)
    assert result.visual_sync_blocks == (1,)
    updated = json.loads((root / "internal" / "speaker_script.json").read_text(encoding="utf-8"))
    sections = {item["slide_id"]: item for item in updated["sections"]}
    assert sections["slide-001"]["narration"] == _narration()
    assert sections["slide-002"]["narration"] == "相邻单元保持原样。"
    log = (root / "internal" / "qa" / "unit_expansions.jsonl").read_text(encoding="utf-8")
    assert "unit-101" in log and "evidence-001" in log


@pytest.mark.parametrize(
    "overrides",
    [
        {"narration": "太短。"},
        {"visual_sync": []},
        {"claims_used": ["claim-999"]},
        {"evidence_used": ["evidence-999"]},
        {"narration": _narration() + "这里凭空出现 999。"},
    ],
)
def test_invalid_expansions_leave_the_script_untouched(tmp_path, overrides):
    root, config, content, unit, script, outline, ledger, claims = _project(tmp_path)
    before = (root / "internal" / "speaker_script.json").read_bytes()

    with pytest.raises(ValidationFailure):
        _expand(root, config, content, unit, script, outline, ledger, claims, _payload(**overrides))

    assert (root / "internal" / "speaker_script.json").read_bytes() == before


def test_internal_ids_are_stripped_and_recorded(tmp_path):
    root, config, content, unit, script, outline, ledger, claims = _project(tmp_path)
    payload = _payload(narration="claim-001 " + _narration())

    result = _expand(root, config, content, unit, script, outline, ledger, claims, payload)

    assert result.stripped_ids == ("claim-001",)
    updated = json.loads((root / "internal" / "speaker_script.json").read_text(encoding="utf-8"))
    narration = updated["sections"][0]["narration"]
    assert "claim-001" not in narration
    assert "已有主张" in narration
