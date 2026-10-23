import json

import pytest

from content_studio.content import generate_public_content
from content_studio.errors import ValidationFailure
from content_studio.models import (
    ContentOutline,
    EvidenceLedger,
    FigureBlock,
    OutlineSection,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    SourceRecord,
    SourceRegistry,
)
from content_studio.providers.base import ModelProvider


class _StubProvider(ModelProvider):
    name = "stub"
    model = "stub-model"

    def __init__(self, content: PublicContent) -> None:
        self._content = content
        self.requests = []

    def generate(self, request):  # pragma: no cover - the helper is not used here
        raise AssertionError("generate_structured is the only entry point under test")

    def generate_structured(self, request, schema):
        self.requests.append(request)
        return self._content


def _config() -> ProjectConfig:
    return ProjectConfig(project_id="figure-test", title="图表测试")


def _outline() -> ContentOutline:
    return ContentOutline(
        project_id="figure-test",
        title="图表测试",
        sections=[
            OutlineSection(slide_id="slide-001", title="第一节", estimated_minutes=5),
        ],
        total_minutes=5,
    )


def _registry() -> SourceRegistry:
    return SourceRegistry(
        project_id="figure-test",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="示例来源",
                kind="markdown",
                origin="input/sample.md",
            )
        ],
    )


def _content(path: str) -> PublicContent:
    return PublicContent(
        project_id="figure-test",
        title="图表测试",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[ParagraphBlock(text="正文"), FigureBlock(path=path, alt="缺失的图")],
                source_ids=["source-001"],
            )
        ],
    )


def test_missing_figure_blocks_are_dropped_and_traced(tmp_path):
    generated = generate_public_content(
        tmp_path,
        _config(),
        _outline(),
        EvidenceLedger(project_id="figure-test"),
        _registry(),
        _StubProvider(_content("assets/missing.png")),
    )

    assert [block.type for slide in generated.slides for block in slide.body] == ["paragraph"]
    saved = json.loads((tmp_path / "content" / "public_content.json").read_text(encoding="utf-8"))
    assert all(block["type"] != "figure" for slide in saved["slides"] for block in slide["body"])

    trace = json.loads(
        (tmp_path / "internal" / "qa" / "generation_trace.json").read_text(encoding="utf-8")
    )
    assert trace[-1]["dropped_figures"] == ["assets/missing.png"]


def test_existing_figure_blocks_are_kept(tmp_path):
    (tmp_path / "content" / "charts").mkdir(parents=True)
    (tmp_path / "content" / "charts" / "figure.svg").write_text("<svg/>", encoding="utf-8")

    generated = generate_public_content(
        tmp_path,
        _config(),
        _outline(),
        EvidenceLedger(project_id="figure-test"),
        _registry(),
        _StubProvider(_content("charts/figure.svg")),
    )

    assert [block.type for slide in generated.slides for block in slide.body] == [
        "paragraph",
        "figure",
    ]


def test_prompt_forbids_internal_ids_in_source_ids(tmp_path):
    provider = _StubProvider(_content("assets/missing.png"))
    generate_public_content(
        tmp_path,
        _config(),
        _outline(),
        EvidenceLedger(project_id="figure-test"),
        _registry(),
        provider,
    )
    request = provider.requests[0]
    system = request.messages[0].content
    user = request.messages[1].content
    assert "禁止填写" in system and "evidence-xxx" in system
    assert "不要把 evidence-xxx 写入 source_ids" in user
    assert "source-001" in user


def test_evidence_ids_in_source_ids_are_rejected(tmp_path):
    content = PublicContent(
        project_id="figure-test",
        title="图表测试",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[ParagraphBlock(text="正文")],
                source_ids=["evidence-001"],
            )
        ],
    )
    with pytest.raises(ValidationFailure, match="unknown source ids"):
        generate_public_content(
            tmp_path,
            _config(),
            _outline(),
            EvidenceLedger(project_id="figure-test"),
            _registry(),
            _StubProvider(content),
        )
