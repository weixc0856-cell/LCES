"""Duration budgets: weighted allocation, estimate/measurement separation."""

from __future__ import annotations

from pathlib import Path

from content_studio.course_quality import TimingEvidence
from content_studio.duration import build_duration_budget
from content_studio.models import (
    CheckBlock,
    ContentOutline,
    EvidenceLedger,
    EvidenceRecord,
    FormulaBlock,
    OutlineSection,
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    ScriptSection,
    SpeakerScript,
    SvgBlock,
)
from content_studio.units import materialize_course
from content_studio.utils import sha256_file, utc_now, write_json


def _content() -> PublicContent:
    return PublicContent(
        project_id="duration-demo",
        title="时长预算课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="简单概念",
                body=[ParagraphBlock(text="一句话说明。"), CheckBlock(question="q1", answer="a1")],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-002",
                title="复杂结构",
                body=[
                    ParagraphBlock(text="先看结构。"),
                    SvgBlock(path="content/figures/arch.svg", alt="结构图"),
                    FormulaBlock(latex="x+y"),
                    CheckBlock(question="q2", answer="a2"),
                ],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-003",
                title="公式推导",
                body=[
                    ParagraphBlock(text="开始推导。"),
                    FormulaBlock(latex="a=b"),
                    FormulaBlock(latex="b=c"),
                    CheckBlock(question="q3", answer="a3"),
                ],
                source_ids=["source-001"],
            ),
        ],
    )


def _outline() -> ContentOutline:
    return ContentOutline(
        project_id="duration-demo",
        title="时长预算课程",
        sections=[
            OutlineSection(
                slide_id=f"slide-{index:03d}",
                title=f"第 {index} 节",
                learning_objectives=[f"目标 {index}a", f"目标 {index}b"],
                key_points=[f"概念 {index}a", f"概念 {index}b", f"概念 {index}c"],
                evidence_ids=["evidence-001"],
                estimated_minutes=1.0,
            )
            for index in (1, 2, 3)
        ],
        total_minutes=3.0,
    )


def _script() -> SpeakerScript:
    return SpeakerScript(
        project_id="duration-demo",
        sections=[
            ScriptSection(slide_id="slide-001", narration="短讲稿。", estimated_seconds=30),
            ScriptSection(slide_id="slide-002", narration="中等讲稿。", estimated_seconds=60),
            ScriptSection(slide_id="slide-003", narration="长讲稿。", estimated_seconds=90),
        ],
        total_estimated_seconds=180,
    )


def _ledger() -> EvidenceLedger:
    return EvidenceLedger(
        project_id="duration-demo",
        records=[
            EvidenceRecord(
                evidence_id="evidence-001",
                source_id="source-001",
                chunk_id="source-001:b0000",
                claim_id="claim-001",
                evidence_type="quote",
                support_relation="supports",
            )
        ],
    )


def _setup(tmp_path: Path):
    root = tmp_path / "project"
    (root / "internal" / "qa").mkdir(parents=True)
    script = _script()
    write_json(root / "internal" / "speaker_script.json", script)
    content = _content()
    master = materialize_course(content, outline=_outline(), script=script, ledger=_ledger())
    return root, content, script, master


def test_budget_is_weighted_not_averaged(tmp_path):
    root, content, script, master = _setup(tmp_path)

    budget = build_duration_budget(root, master, content, script)

    assert budget.total_budget_seconds == 20 * 60
    assert sum(unit.budget_seconds for unit in budget.units) == 20 * 60
    budgets = {unit.scene_id: unit.budget_seconds for unit in budget.units}
    assert budgets["slide-002"] > budgets["slide-001"]
    assert budgets["slide-003"] > budgets["slide-001"]
    assert budget.total_estimated_seconds == 180
    assert budget.measured_valid is False
    assert all(unit.measured_seconds is None for unit in budget.units)


def test_measurement_is_only_used_when_bound_to_the_current_script(tmp_path):
    root, content, script, master = _setup(tmp_path)
    write_json(
        root / "internal" / "qa" / "timing_evidence.json",
        TimingEvidence(
            project_id="duration-demo",
            method="tts_readthrough",
            measured_seconds=300,
            target_minutes=20,
            script_sha256=sha256_file(root / "internal" / "speaker_script.json"),
            scene_seconds={"slide-001": 60, "slide-002": 110, "slide-003": 130},
            generated_at=utc_now(),
        ),
    )

    budget = build_duration_budget(root, master, content, script)

    assert budget.measured_valid is True
    assert budget.total_measured_seconds == 300
    assert [unit.measured_seconds for unit in budget.units] == [60, 110, 130]

    script_path = root / "internal" / "speaker_script.json"
    script_path.write_text(script_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    stale = build_duration_budget(root, master, content, script)
    assert stale.measured_valid is False
    assert stale.total_measured_seconds is None
