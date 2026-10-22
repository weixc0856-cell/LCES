import json

from content_studio.content import generate_public_content
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

    def generate(self, request):  # pragma: no cover - the helper is not used here
        raise AssertionError("generate_structured is the only entry point under test")

    def generate_structured(self, request, schema):
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
