"""CourseMaster materialisation, generated ScenePlan and incremental units."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.models import (
    CheckBlock,
    Claim,
    ContentOutline,
    CourseChapter,
    CourseMaster,
    EvidenceLedger,
    EvidenceRecord,
    FormulaBlock,
    LearningUnit,
    OutlineSection,
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    ScriptSection,
    SourceRecord,
    SourceRegistry,
    SpeakerScript,
    SvgBlock,
)
from content_studio.paths import ensure_project_layout
from content_studio.scenes import (
    PlanScene,
    ScenePlan,
    build_scene_inputs,
    generate_scene_plan,
    merge_scene_plans,
)
from content_studio.units import (
    affected_units,
    delivered_units,
    materialize_course,
    materialize_project_course,
    stale_units,
    write_materialized_course,
)
from content_studio.utils import write_json

TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "public_html"


def _content() -> PublicContent:
    return PublicContent(
        project_id="unit-demo",
        title="单元测试课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="问题",
                body=[ParagraphBlock(text="问题是什么。"), CheckBlock(question="q1", answer="a1")],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-002",
                title="结构",
                body=[
                    ParagraphBlock(text="总体结构。"),
                    SvgBlock(path="content/figures/arch.svg", alt="架构示意图"),
                    FormulaBlock(latex="x+y"),
                ],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-003",
                title="数据",
                body=[
                    ParagraphBlock(text="数据比较。"),
                    CheckBlock(question="q3", answer="a3"),
                ],
                source_ids=["source-001"],
            ),
        ],
    )


def _outline() -> ContentOutline:
    return ContentOutline(
        project_id="unit-demo",
        title="单元测试课程",
        sections=[
            OutlineSection(
                slide_id=f"slide-{index:03d}",
                title=f"第 {index} 节",
                learning_objectives=[f"目标 {index}"],
                key_points=[f"要点 {index}"],
                evidence_ids=["evidence-001"],
                estimated_minutes=1.0,
            )
            for index in (1, 2, 3)
        ],
        total_minutes=3.0,
    )


def _script() -> SpeakerScript:
    return SpeakerScript(
        project_id="unit-demo",
        sections=[
            ScriptSection(
                slide_id=f"slide-{index:03d}",
                narration=f"第 {index} 段讲稿。",
                estimated_seconds=60,
            )
            for index in (1, 2, 3)
        ],
        total_estimated_seconds=180,
    )


def _ledger() -> EvidenceLedger:
    return EvidenceLedger(
        project_id="unit-demo",
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


def _claims() -> list[Claim]:
    return [Claim(claim_id="claim-001", statement="有依据的主张", claim_type="fact")]


def _blueprint() -> CourseMaster:
    return CourseMaster(
        project_id="unit-demo",
        title="单元测试课程",
        chapters=[CourseChapter(chapter_id="chapter-001", title="论文覆盖", unit_ids=["unit-001"])],
        units=[
            LearningUnit(
                unit_id="unit-001",
                chapter_id="chapter-001",
                title="论文单元",
                unit_type="concept",
                estimated_minutes=1.0,
            )
        ],
        coverage=[],
    )


def _project(tmp_path: Path):
    root = ensure_project_layout(tmp_path / "project")
    (root / "project.yaml").write_text(
        "project_id: unit-demo\ntitle: 单元测试课程\n", encoding="utf-8"
    )
    content = _content()
    write_json(root / "content" / "public_content.json", content)
    write_json(root / "content" / "outline.json", _outline())
    write_json(root / "internal" / "speaker_script.json", _script())
    write_json(
        root / "internal" / "claims.json", [claim.model_dump(mode="json") for claim in _claims()]
    )
    write_json(
        root / "internal" / "source_registry.json",
        SourceRegistry(
            project_id="unit-demo",
            sources=[
                SourceRecord(
                    source_id="source-001",
                    title="Source",
                    kind="text",
                    origin="input/source.md",
                    local_path="internal/sources/source-001.txt",
                )
            ],
        ),
    )
    # The ledger is written as CSV by the pipeline; tests build the object and
    # serialise the minimal columns the loader understands.
    header = (
        "evidence_id,source_id,chunk_id,claim_id,evidence_type,locator,source_excerpt,"
        "support_relation,verification_status,quote_status,reviewer,checked_at,notes,structured_json\n"
    )
    row = (
        "evidence-001,source-001,source-001:b0000,claim-001,quote,Abstract,"
        '"quote text",supports,unverified,unverified,,,\n'
    )
    (root / "internal" / "evidence_ledger.csv").write_text(header + row, encoding="utf-8")
    return root, content


def test_materialize_keeps_blueprint_and_adds_scene_units():
    master = materialize_course(
        _content(),
        outline=_outline(),
        script=_script(),
        ledger=_ledger(),
        claims=_claims(),
        blueprint=_blueprint(),
    )

    assert len(master.chapters) == 2
    assert master.chapters[-1].chapter_id == "chapter-900"
    units = delivered_units(master)
    assert [unit.unit_id for unit in units] == ["unit-101", "unit-102", "unit-103"]
    assert [unit.scene_ids for unit in units] == [["slide-001"], ["slide-002"], ["slide-003"]]
    assert units[0].objectives == ["目标 1"]
    assert units[0].claim_ids == ["claim-001"]
    assert units[1].visual_requirements == ["结构图", "公式推导"]
    assert units[0].prerequisites == []
    assert units[1].prerequisites == ["unit-101"]
    assert all(unit.input_sha256 for unit in units)
    assert all(unit.estimated_minutes == 1.0 for unit in units)


def test_materialization_is_deterministic():
    first = materialize_course(_content(), outline=_outline(), script=_script(), ledger=_ledger())
    second = materialize_course(_content(), outline=_outline(), script=_script(), ledger=_ledger())
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_generated_scene_plan_covers_every_block_and_puts_checks_last():
    master = materialize_course(_content(), outline=_outline(), script=_script(), ledger=_ledger())
    plan = generate_scene_plan(master, _content())

    assert set(plan.scenes) == {"slide-001", "slide-002", "slide-003"}
    for slide in _content().slides:
        scene = plan.scenes[slide.slide_id]
        assert [step.block for step in scene.steps] == list(range(len(slide.body)))
        check_indexes = [index for index, block in enumerate(slide.body) if block.type == "check"]
        for check_index in check_indexes:
            assert scene.steps[-1].block == check_index
            assert scene.steps[-1].effect == "hold"
        assert all(step.duration_ms >= 800 for step in scene.steps)
        assert all(step.label for step in scene.steps)
    assert plan.scenes["slide-001"].unit_id == "unit-101"
    assert plan.scenes["slide-002"].scene_type == "structure"
    assert plan.scenes["slide-002"].claim_refs == ["claim-001"]


def test_authored_plan_only_overrides_the_scenes_it_names():
    master = materialize_course(_content(), outline=_outline(), script=_script())
    generated = generate_scene_plan(master, _content())
    authored = ScenePlan(scenes={"slide-001": PlanScene(scene_type="summary")})

    merged = merge_scene_plans(generated, authored)

    assert merged.scenes["slide-001"].scene_type == "summary"
    assert merged.scenes["slide-002"] == generated.scenes["slide-002"]


def test_stale_detection_follows_a_claim_to_every_referencing_unit(tmp_path):
    root, content = _project(tmp_path)
    master = materialize_project_course(root, content)
    write_materialized_course(root, master)
    assert stale_units(root, content, master) == []

    claims = json.loads((root / "internal" / "claims.json").read_text(encoding="utf-8"))
    claims[0]["statement"] = "主张已被修改"
    write_json(root / "internal" / "claims.json", claims)

    assert stale_units(root, content, master) == ["unit-101", "unit-102", "unit-103"]
    assert affected_units(master, "claim-001") == ["unit-101", "unit-102", "unit-103"]


def test_build_inputs_do_not_need_an_authored_plan(tmp_path):
    root, content = _project(tmp_path)
    inputs = build_scene_inputs(root, content)

    assert len(inputs.scenes) == 3
    assert len(inputs.generated_plan.scenes) == 3
    assert all(scene.steps for scene in inputs.scenes)
    assert inputs.scenes[0].contract.data["unit_id"] == "unit-101"


def test_cli_regenerates_one_unit_and_reports_impact(tmp_path):
    root, _content_before = _project(tmp_path)
    master = materialize_project_course(root, _content())
    write_materialized_course(root, master)
    runner = CliRunner()

    claims = json.loads((root / "internal" / "claims.json").read_text(encoding="utf-8"))
    claims[0]["statement"] = "主张已被修改"
    write_json(root / "internal" / "claims.json", claims)

    impact = runner.invoke(app, ["plan-impact", str(root)])
    assert impact.exit_code == 0
    assert "失效单元" in impact.output

    result = runner.invoke(app, ["generate", str(root), "--unit", "unit-101", "--provider", "mock"])
    assert result.exit_code == 0, result.output
    assert "已重生成单元" in result.output

    updated = json.loads((root / "content" / "public_content.json").read_text(encoding="utf-8"))
    assert updated["slides"][0]["title"].startswith("MOCK 单场景")
    assert updated["slides"][1]["title"] == "结构"

    after = runner.invoke(app, ["plan-impact", str(root)])
    assert after.exit_code == 0
    assert "unit-101" not in after.output
    assert "unit-102" in after.output

    skipped = runner.invoke(
        app, ["generate", str(root), "--unit", "unit-101", "--provider", "mock"]
    )
    assert skipped.exit_code == 0
    assert "跳过" in skipped.output
