"""Scene contract derivation: one playable, validated contract per slide."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio.errors import RenderError
from content_studio.models import (
    CheckBlock,
    Claim,
    ContentOutline,
    OutlineSection,
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    ScriptSection,
    SpeakerScript,
)
from content_studio.paths import ensure_project_layout
from content_studio.rendering import build_public_html
from content_studio.scenes import (
    PlanScene,
    PlanStep,
    ScenePlan,
    derive_deck_scenes,
)
from content_studio.utils import write_json

TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "public_html"


def _content() -> PublicContent:
    return PublicContent(
        project_id="scene-demo",
        title="场景测试课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="问题",
                body=[
                    ParagraphBlock(text="先说明问题。"),
                    CheckBlock(question="问题是什么？", answer="示例答案。"),
                ],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-002",
                title="机制",
                body=[
                    ParagraphBlock(text="再说明机制。"),
                    ParagraphBlock(text="机制的第二段。"),
                    CheckBlock(question="机制是什么？", answer="示例答案。"),
                ],
                source_ids=["source-001"],
            ),
        ],
    )


def _outline() -> ContentOutline:
    return ContentOutline(
        project_id="scene-demo",
        title="场景测试课程",
        sections=[
            OutlineSection(
                slide_id="slide-001",
                title="问题",
                learning_objectives=["说清问题"],
                evidence_ids=[],
                estimated_minutes=1.0,
            ),
            OutlineSection(
                slide_id="slide-002",
                title="机制",
                learning_objectives=["说清机制", "说清代价"],
                evidence_ids=[],
                estimated_minutes=1.0,
            ),
        ],
        total_minutes=2.0,
    )


def _script() -> SpeakerScript:
    return SpeakerScript(
        project_id="scene-demo",
        sections=[
            ScriptSection(slide_id="slide-001", narration="第一段讲稿。", estimated_seconds=10),
            ScriptSection(slide_id="slide-002", narration="第二段讲稿。", estimated_seconds=10),
        ],
        total_estimated_seconds=20,
    )


def test_one_contract_per_slide_with_steps_and_state():
    scenes = derive_deck_scenes(_content(), outline=_outline(), script=_script(), claims=[])

    assert [scene.contract.scene_id for scene in scenes] == ["slide-001", "slide-002"]
    first = scenes[0]
    assert first.contract.scene_type == "concept"
    assert len(first.steps) == 2
    assert [step.block_index for step in first.steps] == [0, 1]
    assert first.contract.duration_ms == sum(step.duration_ms for step in first.steps)
    assert first.contract.entry_state == {"step": 0, "revealed_blocks": 0}
    assert first.contract.exit_state == {"step": 2, "revealed_blocks": 2}
    assert first.contract.reset_policy == "replay"
    assert first.contract.narration_ref.endswith("#slide-001")
    assert first.contract.objective_ids == ["slide-001-objective-00"]
    assert first.objectives == ("说清问题",)
    assert "narration_mapped" in first.contract.required_checks
    assert first.contract.data["canvas"] == {"width": 1920, "height": 1080}


def test_plan_controls_type_labels_effects_and_durations():
    plan = ScenePlan(
        scenes={
            "slide-002": PlanScene(
                scene_type="process",
                steps=[
                    PlanStep(block=2, label="先看结论", effect="hold", duration_ms=2000),
                    PlanStep(block=0, label="再回到机制", effect="focus", duration_ms=3000),
                ],
            )
        }
    )

    scenes = derive_deck_scenes(_content(), outline=_outline(), script=_script(), plan=plan)

    second = scenes[1]
    assert second.contract.scene_type == "process"
    assert [step.block_index for step in second.steps] == [2, 0, 1]
    assert second.steps[0].label == "先看结论"
    assert second.steps[0].effect == "hold"
    assert second.steps[0].duration_ms == 2000
    assert second.steps[1].effect == "focus"
    # A block the plan forgot is still revealed, never silently dropped.
    assert second.steps[2].block_index == 1


def test_plan_cannot_target_a_missing_block():
    plan = ScenePlan(scenes={"slide-001": PlanScene(steps=[PlanStep(block=9)])})

    with pytest.raises(RenderError, match="targets block 9"):
        derive_deck_scenes(_content(), plan=plan)


def test_plan_cannot_animate_one_block_twice():
    plan = ScenePlan(scenes={"slide-001": PlanScene(steps=[PlanStep(block=0), PlanStep(block=0)])})

    with pytest.raises(RenderError, match="animated twice"):
        derive_deck_scenes(_content(), plan=plan)


def test_plan_cannot_name_an_unknown_scene():
    plan = ScenePlan(scenes={"slide-999": PlanScene()})

    with pytest.raises(RenderError, match="unknown slides"):
        derive_deck_scenes(_content(), plan=plan)


def test_plan_claim_reference_must_exist():
    claims = [Claim(claim_id="claim-001", statement="有依据的主张", claim_type="fact")]
    plan = ScenePlan(scenes={"slide-001": PlanScene(claim_refs=["claim-999"])})

    with pytest.raises(RenderError, match="unknown claim references: claim-999"):
        derive_deck_scenes(_content(), claims=claims, plan=plan)


def test_script_must_cover_every_scene():
    script = SpeakerScript(
        project_id="scene-demo",
        sections=[ScriptSection(slide_id="slide-001", narration="只有第一段。")],
    )

    with pytest.raises(RenderError, match="slide-002"):
        derive_deck_scenes(_content(), script=script)


def test_build_embeds_scene_contracts_and_writes_the_report(tmp_path):
    root = ensure_project_layout(tmp_path / "project")
    content = _content()
    write_json(root / "content" / "public_content.json", content)
    write_json(root / "content" / "outline.json", _outline())
    write_json(root / "internal" / "speaker_script.json", _script())

    build_public_html(
        content, TEMPLATES, root / "build" / "slides" / "index.html", project_dir=root
    )

    report = json.loads(
        (root / "internal" / "qa" / "scene_contracts.json").read_text(encoding="utf-8")
    )
    assert [scene["scene_id"] for scene in report["scenes"]] == ["slide-001", "slide-002"]
    html = (root / "build" / "slides" / "index.html").read_text(encoding="utf-8")
    assert 'id="sceneData"' in html
    assert '"scene_id": "slide-001"' in html
    assert 'data-scene-id="slide-002"' in html
    assert 'data-block-index="1"' in html


def test_derivation_and_html_are_deterministic(tmp_path):
    content = _content()
    first = derive_deck_scenes(content, outline=_outline(), script=_script())
    second = derive_deck_scenes(content, outline=_outline(), script=_script())
    assert [scene.as_payload() for scene in first] == [scene.as_payload() for scene in second]

    root = ensure_project_layout(tmp_path / "project")
    write_json(root / "content" / "public_content.json", content)
    write_json(root / "content" / "outline.json", _outline())
    write_json(root / "internal" / "speaker_script.json", _script())
    one = root / "build" / "one.html"
    two = root / "build" / "two.html"
    build_public_html(content, TEMPLATES, one, project_dir=root)
    build_public_html(content, TEMPLATES, two, project_dir=root)
    assert one.read_text(encoding="utf-8") == two.read_text(encoding="utf-8")
