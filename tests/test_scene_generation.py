"""Single-scene regeneration: only the named slide changes, failures write nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.content import regenerate_slide
from content_studio.errors import ValidationFailure
from content_studio.models import (
    CheckBlock,
    ContentOutline,
    EvidenceLedger,
    OutlineSection,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    ScriptSection,
    SourceRecord,
    SourceRegistry,
    SpeakerScript,
)
from content_studio.paths import ensure_project_layout
from content_studio.providers.base import GenerationRequest, GenerationResult, ModelProvider
from content_studio.utils import write_json


class StubProvider(ModelProvider):
    name = "stub"
    model = "stub-1"

    def __init__(self, *, slide_id: str | None = None, source_ids: list[str] | None = None):
        self._slide_id = slide_id
        self._source_ids = source_ids if source_ids is not None else ["source-001"]

    def generate(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise AssertionError("single-scene generation uses structured output only")

    def generate_structured(self, request: GenerationRequest, schema):
        slide_id = self._slide_id or str(request.metadata["slide_id"])
        if schema is PublicSlide:
            return PublicSlide(
                slide_id=slide_id,
                title="新的场景标题",
                body=[ParagraphBlock(text="这是重新生成的场景正文。")],
                source_ids=self._source_ids,
            )
        if schema is ScriptSection:
            return ScriptSection(
                slide_id=slide_id,
                narration="这是重新生成的场景口播稿。",
                estimated_seconds=1,
            )
        raise AssertionError(f"unexpected schema {schema.__name__}")


def _content() -> PublicContent:
    return PublicContent(
        project_id="scene-demo",
        title="场景测试课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一幕",
                body=[ParagraphBlock(text="第一幕正文。"), CheckBlock(question="q1", answer="a1")],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-002",
                title="第二幕",
                body=[ParagraphBlock(text="第二幕正文。"), CheckBlock(question="q2", answer="a2")],
                source_ids=["source-001"],
            ),
            PublicSlide(
                slide_id="slide-003",
                title="第三幕",
                body=[ParagraphBlock(text="第三幕正文。"), CheckBlock(question="q3", answer="a3")],
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
                slide_id=f"slide-{index:03d}",
                title=f"第 {index} 幕",
                learning_objectives=[f"目标 {index}"],
                estimated_minutes=1.0,
            )
            for index in (1, 2, 3)
        ],
        total_minutes=3.0,
    )


def _script() -> SpeakerScript:
    return SpeakerScript(
        project_id="scene-demo",
        sections=[
            ScriptSection(slide_id=f"slide-{index:03d}", narration=f"第 {index} 幕讲稿。")
            for index in (1, 2, 3)
        ],
        total_estimated_seconds=30,
    )


def _project(tmp_path: Path):
    root = ensure_project_layout(tmp_path / "project")
    content = _content()
    write_json(root / "content" / "public_content.json", content)
    write_json(root / "content" / "outline.json", _outline())
    write_json(root / "internal" / "speaker_script.json", _script())
    write_json(
        root / "internal" / "source_registry.json",
        SourceRegistry(
            project_id="scene-demo",
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
    config = ProjectConfig(project_id="scene-demo", title="场景测试课程")
    return root, config, content, _outline(), EvidenceLedger(project_id="scene-demo")


def test_only_the_named_scene_and_its_narration_change(tmp_path):
    root, config, content, outline, ledger = _project(tmp_path)
    registry = SourceRegistry(
        project_id="scene-demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Source",
                kind="text",
                origin="input/source.md",
                local_path="internal/sources/source-001.txt",
            )
        ],
    )

    updated = regenerate_slide(root, config, outline, ledger, registry, StubProvider(), "slide-002")

    by_id = {slide.slide_id: slide for slide in updated.slides}
    assert by_id["slide-002"].title == "新的场景标题"
    assert by_id["slide-001"].model_dump() == content.slides[0].model_dump()
    assert by_id["slide-003"].model_dump() == content.slides[2].model_dump()

    script = SpeakerScript.model_validate_json(
        (root / "internal" / "speaker_script.json").read_text(encoding="utf-8")
    )
    sections = {section.slide_id: section for section in script.sections}
    assert sections["slide-002"].narration == "这是重新生成的场景口播稿。"
    assert sections["slide-001"].narration == "第 1 幕讲稿。"
    assert script.total_estimated_seconds == sum(item.estimated_seconds for item in script.sections)


def test_wrong_scene_from_the_model_leaves_the_course_untouched(tmp_path):
    root, config, _content_before, outline, ledger = _project(tmp_path)
    registry = SourceRegistry(
        project_id="scene-demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Source",
                kind="text",
                origin="input/source.md",
                local_path="internal/sources/source-001.txt",
            )
        ],
    )
    public_before = (root / "content" / "public_content.json").read_bytes()
    script_before = (root / "internal" / "speaker_script.json").read_bytes()

    with pytest.raises(ValidationFailure, match="while regenerating slide-002"):
        regenerate_slide(
            root,
            config,
            outline,
            ledger,
            registry,
            StubProvider(slide_id="slide-001"),
            "slide-002",
        )

    assert (root / "content" / "public_content.json").read_bytes() == public_before
    assert (root / "internal" / "speaker_script.json").read_bytes() == script_before


def test_unknown_scene_is_refused_before_generation(tmp_path):
    root, config, _content_before, outline, ledger = _project(tmp_path)
    registry = SourceRegistry(project_id="scene-demo", sources=[])

    with pytest.raises(ValidationFailure, match="not part of this course"):
        regenerate_slide(root, config, outline, ledger, registry, StubProvider(), "slide-999")


def test_unknown_public_source_is_refused(tmp_path):
    root, config, _content_before, outline, ledger = _project(tmp_path)
    registry = SourceRegistry(
        project_id="scene-demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Source",
                kind="text",
                origin="input/source.md",
                local_path="internal/sources/source-001.txt",
            )
        ],
    )

    with pytest.raises(ValidationFailure, match="unknown source ids"):
        regenerate_slide(
            root,
            config,
            outline,
            ledger,
            registry,
            StubProvider(source_ids=["source-404"]),
            "slide-002",
        )
