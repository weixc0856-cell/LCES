import pytest
from bs4 import BeautifulSoup

from content_studio.errors import RenderError
from content_studio.models import (
    BulletsBlock,
    FormulaBlock,
    InteractiveBlock,
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    ReadingEdition,
    ReadingSection,
    SvgBlock,
    TableBlock,
)
from content_studio.paths import template_dir
from content_studio.rendering import _prepare_blocks, build_public_html, build_reading_html


def _content() -> PublicContent:
    return PublicContent(
        project_id="test-course",
        title="公开课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="标题",
                body=[
                    ParagraphBlock(text="公开正文"),
                    TableBlock(columns=["指标", "数值"], rows=[["延迟", "1.2 ms"]]),
                ],
                source_ids=["source-001"],
            )
        ],
    )


def test_public_builder_renders_only_public_model(tmp_path):
    output = build_public_html(_content(), template_dir(), tmp_path / "index.html")
    html = output.read_text(encoding="utf-8")
    assert "公开正文" in html
    assert "<table>" in html
    assert "source-001" in html
    assert "speaker_script" not in html
    assert "口播稿" not in html


def test_reading_edition_renders(tmp_path):
    edition = ReadingEdition(
        project_id="test-course",
        title="阅读版",
        abstract="摘要正文",
        sections=[
            ReadingSection(slide_id="slide-001", title="第一节", paragraphs=["深入阅读内容"])
        ],
        references=["Example et al. 2026"],
    )
    output = build_reading_html(edition, template_dir(), tmp_path / "reading.html")
    html = output.read_text(encoding="utf-8")
    assert "深入阅读内容" in html
    assert "Example et al. 2026" in html


def test_bullets_block_renders(tmp_path):
    """`items` is also a dict method; the template must read the key, not the method."""

    content = PublicContent(
        project_id="test-course",
        title="要点",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="列表",
                body=[BulletsBlock(items=["第一点", "第二点"])],
            )
        ],
    )
    html = build_public_html(content, template_dir(), tmp_path / "index.html").read_text(
        encoding="utf-8"
    )
    assert "<li>第一点</li>" in html
    assert "<li>第二点</li>" in html


def test_public_builder_escapes_html(tmp_path):
    content = PublicContent(
        project_id="test-course",
        title="<script>alert(1)</script>",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="安全",
                body=[ParagraphBlock(text="<img src=x onerror=alert(1)>")],
            )
        ],
    )
    html = build_public_html(content, template_dir(), tmp_path / "index.html").read_text(
        encoding="utf-8"
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_formula_block_is_typeset_not_raw_latex(tmp_path):
    content = PublicContent(
        project_id="test-course",
        title="公式",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="注意力",
                body=[
                    FormulaBlock(
                        latex=r"\mathrm{Attention}(Q,K,V)=\mathrm{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V",
                        explanation="缩放点积注意力",
                        label="注意力公式",
                    )
                ],
                source_ids=["source-001"],
            )
        ],
    )
    html = build_public_html(content, template_dir(), tmp_path / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'class="m-frac"' in html
    assert 'role="math"' in html
    soup = BeautifulSoup(html, "html.parser")
    visible = soup.select_one(".formula").get_text(" ", strip=True)
    assert "\\" not in visible
    assert "Attention" in visible


def test_interactive_block_renders_scene_without_page_logic(tmp_path):
    content = PublicContent(
        project_id="test-course",
        title="实验室",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="方差",
                body=[
                    InteractiveBlock(
                        scene="variance-saturation",
                        title="方差饱和",
                        description="拖动 d_k",
                        params={"dk": 64},
                    )
                ],
            )
        ],
    )
    html = build_public_html(content, template_dir(), tmp_path / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'data-scene="variance-saturation"' in html
    assert "data-params=" in html
    assert "<canvas" in html


def test_svg_block_is_inlined_and_missing_file_fails(tmp_path):
    project = tmp_path / "project"
    figures = project / "content" / "figures"
    figures.mkdir(parents=True)
    (figures / "diagram.svg").write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10"/></svg>'
        ),
        encoding="utf-8",
    )
    block = SvgBlock(path="content/figures/diagram.svg", alt="示意图", caption="图")
    data = block.model_dump(mode="json")
    _prepare_blocks([block], [data], project_dir=project, page_label="test")
    assert "<svg" in data["svg_html"]
    assert 'aria-label="示意图"' in data["svg_html"]

    missing = SvgBlock(path="content/figures/missing.svg", alt="缺失")
    with pytest.raises(RenderError):
        _prepare_blocks(
            [missing], [missing.model_dump(mode="json")], project_dir=project, page_label="test"
        )


def test_reading_edition_body_blocks_render(tmp_path):
    edition = ReadingEdition(
        project_id="test-course",
        title="阅读版",
        abstract="摘要",
        sections=[
            ReadingSection(
                slide_id="slide-001",
                title="第一节",
                body=[
                    ParagraphBlock(text="深度正文"),
                    FormulaBlock(latex=r"\mathrm{Var}(q\cdot k)=d_k"),
                ],
            )
        ],
        nomenclature=[
            {"symbol": "d_k", "meaning": "键维度", "shape": "64"},
        ],
    )
    html = build_reading_html(edition, template_dir(), tmp_path / "reading.html").read_text(
        encoding="utf-8"
    )
    assert "深度正文" in html
    soup = BeautifulSoup(html, "html.parser")
    formula = soup.select_one(".formula").get_text(" ", strip=True)
    assert "\\" not in formula
    assert "Var" in formula
    assert "符号、含义与张量形状" in html
